"""Candidate sites for phase 2 enrichment.

Phase 2 asks a model to judge one function at a time. It needs a bounded,
deterministic list of functions that are actually reachable from an entrypoint,
not the whole repository. This module produces that list.

What it is not: a parser. Python uses `ast`; JavaScript and TypeScript use
brace matching over regex-found headers. The JavaScript side is approximate by
design and documented in references/entrypoints.md. A site whose bounds are
wrong produces evidence that fails `pareto-triage validate`, which is a visible
failure rather than a silent one.
"""

import ast
import re

JS_EXT = {".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs"}
PY_EXT = {".py"}

LANG_BY_EXT = {
    ".ts": "ts", ".tsx": "ts", ".mts": "ts", ".cts": "ts",
    ".js": "js", ".jsx": "js", ".mjs": "js", ".cjs": "js",
    ".py": "py",
}

MAX_SITES_DEFAULT = 400
MAX_SOURCE_LINES = 300

JS_KEYWORDS = {
    "if", "for", "while", "switch", "catch", "return", "function", "else", "do",
    "try", "with", "typeof", "new", "delete", "await", "yield", "class", "super",
    "import", "export", "default", "constructor",
}

IMPORT_LINE_RES = [
    re.compile(r"^\s*import\s.+$", re.M),
    re.compile(r"^\s*from\s+\S+\s+import\s.+$", re.M),
    re.compile(r"^\s*(?:const|let|var)\s+[\w${}\s,]+=\s*require\(.+$", re.M),
]

# Client construction and middleware registration. A timeout or retry policy
# usually lives here, not in the function body.
CLIENT_LINE_RES = [
    re.compile(r"^.*\bnew\s+[A-Z]\w*(?:Client|Pool|Queue|Producer|Consumer|Session)\s*\(.*$", re.M),
    re.compile(r"^.*=\s*(?:express|fastify|FastAPI|Flask|Router|createClient|createPool)\s*\(.*$", re.M),
    re.compile(r"^.*\b(?:axios\.create|httpx\.Client|requests\.Session)\s*\(.*$", re.M),
]
MIDDLEWARE_LINE_RES = [
    re.compile(r"^.*\b(?:app|router|server|api)\s*\.\s*use\s*\(.*$", re.M),
    re.compile(r"^.*@\s*\w+\s*\.\s*middleware\b.*$", re.M),
    re.compile(r"^.*\badd_middleware\s*\(.*$", re.M),
]

SURROUNDING_LIMIT = 60

JS_HEADERS = [
    (re.compile(r"^[ \t]*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)\s*\(", re.M),
     "brace"),
    (re.compile(r"^[ \t]*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=\n]+)?=\s*"
                r"(?:async\s+)?function\s*\*?\s*[A-Za-z_$\s]*\(", re.M),
     "brace"),
    (re.compile(r"^[ \t]*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=\n]+)?=\s*"
                r"(?:async\s+)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>", re.M),
     "arrow"),
    (re.compile(r"^[ \t]*(?:async\s+)?([A-Za-z_$][\w$]*)\s*\([^;{}\n]*\)\s*\{", re.M),
     "brace"),
]

# Handlers written inline at the route call. In an Express codebase this is
# where most of the logic lives, so a site list without them misses the target.
INLINE_ROUTE_RES = [
    re.compile(r"\b(?:app|router|server|api|fastify)\s*\.\s*(get|post|put|patch|delete|all)\s*\(\s*"
               r"(['\"`])([^'\"`]+)\2\s*,\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>", re.M),
    re.compile(r"\b(?:app|router|server|api|fastify)\s*\.\s*(get|post|put|patch|delete|all)\s*\(\s*"
               r"(['\"`])([^'\"`]+)\2\s*,\s*(?:async\s+)?function\s*\*?\s*[A-Za-z_$\s]*\(", re.M),
]


def _line_of(text, index):
    return text.count("\n", 0, index) + 1


def _skip_string(text, index):
    quote = text[index]
    index += 1
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == quote:
            return index + 1
        index += 1
    return index


def _match_brace(text, open_index):
    """Return the index of the brace closing text[open_index], or -1."""
    depth = 0
    index = open_index
    while index < len(text):
        char = text[index]
        if char in "\"'`":
            index = _skip_string(text, index)
            continue
        if char == "/" and text.startswith("//", index):
            newline = text.find("\n", index)
            index = len(text) if newline < 0 else newline
            continue
        if char == "/" and text.startswith("/*", index):
            close = text.find("*/", index + 2)
            index = len(text) if close < 0 else close + 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return -1


def _next_body(text, start, limit):
    """Find the body brace from `start`, giving up at `limit` or a newline run."""
    index = start
    while index < limit:
        char = text[index]
        if char == "{":
            return index
        if char in "\"'`":
            index = _skip_string(text, index)
            continue
        if char == ";":
            return -1
        index += 1
    return -1


def _js_sites(text, rel):
    out = []
    for pattern, kind in JS_HEADERS:
        for match in pattern.finditer(text):
            name = match.group(1)
            if name in JS_KEYWORDS:
                continue
            if kind == "brace":
                open_index = _next_body(text, match.end() - 1, min(len(text), match.end() + 400))
                if open_index < 0:
                    continue
                close_index = _match_brace(text, open_index)
                end = len(text) if close_index < 0 else close_index + 1
            else:
                open_index = _next_body(text, match.end(), min(len(text), match.end() + 400))
                if open_index < 0:
                    newline = text.find("\n", match.end())
                    end = len(text) if newline < 0 else newline
                else:
                    close_index = _match_brace(text, open_index)
                    end = len(text) if close_index < 0 else close_index + 1
            out.append({
                "name": name,
                "start": _line_of(text, match.start()),
                "end": _line_of(text, max(match.start(), end - 1)),
            })

    for pattern in INLINE_ROUTE_RES:
        for match in pattern.finditer(text):
            name = "%s %s" % (match.group(1).upper(), match.group(3))
            cursor = match.end()
            while cursor < len(text) and text[cursor] in " \t":
                cursor += 1
            if cursor < len(text) and text[cursor] == "{":
                close_index = _match_brace(text, cursor)
                end = len(text) if close_index < 0 else close_index + 1
            else:
                newline = text.find("\n", cursor)
                end = len(text) if newline < 0 else newline
            out.append({
                "name": name,
                "start": _line_of(text, match.start()),
                "end": _line_of(text, max(match.start(), end - 1)),
            })

    return out


def _py_sites(text, rel):
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return None, "line %s: %s" % (exc.lineno, exc.msg)

    lines = text.split("\n")
    out = []

    def visit(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                start = child.lineno
                if getattr(child, "decorator_list", None):
                    start = min(d.lineno for d in child.decorator_list)
                out.append({
                    "name": prefix + child.name,
                    "start": start,
                    "end": getattr(child, "end_lineno", None) or child.lineno,
                })
                visit(child, prefix + child.name + ".")
            elif isinstance(child, ast.ClassDef):
                visit(child, prefix + child.name + ".")
            else:
                visit(child, prefix)

    visit(tree, "")
    if not out:
        return out, None
    return out, None


def _surrounding(text, start_line, limit=SURROUNDING_LIMIT):
    """Imports, client construction, and middleware, quoted as-is.

    Returns (text, truncated). Sections are the file's own lines, in file order;
    nothing is summarised, because a summary is a place a model can invent.
    """
    picked = []
    for patterns in (IMPORT_LINE_RES, CLIENT_LINE_RES, MIDDLEWARE_LINE_RES):
        for pattern in patterns:
            for match in pattern.finditer(text):
                line = _line_of(text, match.start())
                if line >= start_line:
                    continue
                picked.append((line, match.group(0).strip()))

    picked.sort()
    seen = set()
    unique = []
    for _, content in picked:
        if content in seen:
            continue
        seen.add(content)
        unique.append(content)

    truncated = len(unique) > limit
    return "\n".join(unique[:limit]), truncated


def extract_sites_collapse(candidates, include_enclosing=False):
    return candidates if include_enclosing else _collapse_nested(candidates)


def _collapse_nested(candidates):
    """Keep the innermost function where sites overlap; remember its containers.

    A site inside another site would otherwise be judged twice for the same
    lines, and two findings on one line inflate a cluster's noisy-OR.
    """
    by_file = {}
    for site in candidates:
        by_file.setdefault(site["file"], []).append(site)

    kept = []
    for rel in sorted(by_file):
        sites = sorted(by_file[rel], key=lambda s: (s["lines"][0], -s["lines"][1]))
        dropped = set()
        for i, outer in enumerate(sites):
            for j, inner in enumerate(sites):
                if i == j or outer is inner:
                    continue
                o_start, o_end = outer["lines"]
                i_start, i_end = inner["lines"]
                contains = o_start <= i_start and i_end <= o_end
                if contains and (o_start, o_end) != (i_start, i_end):
                    dropped.add(i)

        for i, site in enumerate(sites):
            if i in dropped:
                continue
            enclosing = [s["function"] for k, s in enumerate(sites)
                         if k in dropped
                         and s["lines"][0] <= site["lines"][0] and site["lines"][1] <= s["lines"][1]]
            if enclosing:
                record = dict(site)
                record["enclosed_by"] = sorted(set(enclosing), key=lambda n: len(n))
                kept.append(record)
            else:
                kept.append(site)
    return kept


def extract_sites(files, reach_of, max_sites=MAX_SITES_DEFAULT, max_source_lines=MAX_SOURCE_LINES,
                  min_reach=2, include_enclosing=False):
    """Return (sites, summary). Sites are ordered deterministically."""
    candidates = []
    parse_errors = []
    unreachable_files = 0

    for f in files:
        rel = f["rel"]
        ext = f["ext"]
        if ext not in JS_EXT and ext not in PY_EXT:
            continue
        reach = reach_of(rel)
        if reach < min_reach:
            unreachable_files += 1
            continue

        text = f["text"]
        if ext in PY_EXT:
            found, error = _py_sites(text, rel)
            if error:
                parse_errors.append({"file": rel, "reason": error})
                continue
        else:
            found = _js_sites(text, rel)

        lines = text.split("\n")
        for item in found:
            start = max(1, item["start"])
            end = min(item["end"], len(lines))
            if end < start:
                continue
            surrounding, surrounding_truncated = _surrounding(text, start)
            source_lines = lines[start - 1:end]
            truncated = len(source_lines) > max_source_lines
            if truncated:
                source_lines = source_lines[:max_source_lines]
            candidates.append({
                "file": rel,
                "function": item["name"],
                "lines": [start, start + len(source_lines) - 1],
                "lang": LANG_BY_EXT[ext],
                "reach": reach,
                "source": "\n".join(source_lines),
                "surrounding": surrounding,
                "surrounding_truncated": surrounding_truncated,
                "truncated": truncated,
            })

    collapsed = extract_sites_collapse(candidates, include_enclosing)
    collapsed.sort(key=lambda s: (-s["reach"], s["file"], s["lines"][0], s["function"]))
    total = len(collapsed)
    limited = collapsed[:max_sites]

    sites = []
    for index, site in enumerate(limited, start=1):
        record = {"site_id": "s_%03d" % index}
        record.update(site)
        sites.append(record)

    summary = {
        "candidates": total,
        "emitted": len(sites),
        "limit": max_sites,
        "limit_hit": total > max_sites,
        "parse_errors": parse_errors,
        "unreachable_source_files": unreachable_files,
    }
    return sites, summary


def load_sites(path):
    """Read out/context.jsonl into {site_id: site}. Missing file is not an error."""
    from .schema import parse_jsonl

    from pathlib import Path

    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    records, bad = parse_jsonl(text)
    if bad:
        return None
    sites = {}
    for _, record in records:
        if isinstance(record, dict) and record.get("site_id"):
            sites[record["site_id"]] = record
    return sites


def site_contains(site, line):
    start, end = site.get("lines") or (0, 0)
    return start <= line <= end
