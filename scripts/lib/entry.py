"""Entrypoint extraction. Regex based in M0; tree-sitter arrives in M2."""

import json
import posixpath
import re

JS_EXT = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
PY_EXT = {".py"}

def _method_path(m):
    return "%s %s" % (m.group(1).upper(), m.group(3))


def _quote_path(m):
    return "ROUTE %s" % m.group(2)


MIDDLEWARE = [
    ("express", JS_EXT, re.compile(
        r"\b(?:app|router|server|api)\s*\.\s*use\s*\(\s*(['\"`])([^'\"`]+)\1"),
     "USE"),
]

ROUTES = [    ("express", JS_EXT, re.compile(
        r"\b(?:app|router|server|api)\s*\.\s*(get|post|put|patch|delete|all)\s*\(\s*(['\"`])([^'\"`]+)\2"),
     _method_path),
    ("fastify", JS_EXT, re.compile(
        r"\bfastify\s*\.\s*(get|post|put|patch|delete)\s*\(\s*(['\"`])([^'\"`]+)\2"),
     _method_path),
    ("fastify", JS_EXT, re.compile(
        r"\.route\s*\(\s*\{[\s\S]{0,400}?url\s*:\s*(['\"`])([^'\"`]+)\1"),
     _quote_path),
    ("fastapi", PY_EXT, re.compile(
        r"@\s*\w+\s*\.\s*(get|post|put|patch|delete|websocket)\s*\(\s*(['\"])([^'\"]+)\2"),
     _method_path),
    ("flask", PY_EXT, re.compile(
        r"@\s*\w+\s*\.\s*route\s*\(\s*(['\"])([^'\"]+)\1"),
     _quote_path),
    ("flask", PY_EXT, re.compile(
        r"\b\w+\s*\.\s*add_url_rule\s*\(\s*(['\"])([^'\"]+)\1"),
     _quote_path),
]

DJANGO_RE = re.compile(r"(?:^|[^\w.])(?:path|re_path)\s*\(\s*(['\"])([^'\"]+)\1", re.M)
DJANGO_INCLUDE_RE = re.compile(r"(?:^|[^\w.])include\s*\(\s*(['\"])([\w.]+)\1", re.M)

ENTRY_FILE_RE = re.compile(r"(^|/)(index\.(ts|tsx|js|mjs)|__init__\.py)$")
PUBLIC_EXPORT_RES = [
    re.compile(r"^\s*export\s+(?:async\s+)?(?:function|class|const|let|var)\s+([A-Za-z_$][\w$]*)", re.M),
    re.compile(r"^\s*export\s*\{", re.M),
]
NEXT_APP_RE = re.compile(
    r"export\s+(?:async\s+)?(?:const|function)\s+(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\b")
NEXT_APP_PATH = re.compile(r"(^|/)app/.+/route\.[jt]sx?$")
NEXT_PAGES_PATH = re.compile(r"(^|/)pages/api/.+\.(ts|tsx|js|jsx|mjs)$")

CONSUMER_RES = [
    (re.compile(r"\.subscribe\s*\("), "subscribe"),
    (re.compile(r"@(?:app\.task|shared_task)\b"), "celery task"),
    (re.compile(r"\.consume\s*\("), "consume"),
    (re.compile(r"new\s+Consumer\s*\("), "kafka consumer"),
]

CRON_RES = [
    (re.compile(r"cron\.schedule\s*\("), "node-cron"),
    (re.compile(r"schedule\.every\s*\("), "python schedule"),
    (re.compile(r"@scheduled\s*\(", re.I), "scheduled"),
    (re.compile(r"setInterval\s*\("), "setInterval"),
]

CLIENT_JS_RE = re.compile(r"^#!.*\bnode\b")
CLIENT_PY_RE = re.compile(r"^#!.*\bpython[\d.]*\b")
PY_MAIN_RE = re.compile(r"if\s+__name__\s*==\s*['\"]__main__['\"]\s*:")
CLICK_CMD_RE = re.compile(r"@\w+\.command\s*\(")


def _line_of(text, index):
    return text.count("\n", 0, index) + 1


def _collect(pattern, text, rel, make):
    out = []
    for m in pattern.finditer(text):
        out.append({"file": rel, "line": _line_of(text, m.start()), **make(m)})
    return out


def _known_paths(files):
    return {f["rel"] for f in files}


def _resolve_include(rel, module, known):
    parts = [p for p in module.split(".") if p]
    base = posixpath.dirname(rel)
    while True:
        candidate = posixpath.join(base, *parts) + ".py"
        if candidate in known:
            return candidate
        if base in ("", "."):
            return None
        base = posixpath.dirname(base)


def extract_entrypoints(files):
    found = []
    known = _known_paths(files)

    for f in files:
        text = f["text"]
        rel = f["rel"]
        ext = f["ext"]

        for framework, exts, pattern, make in MIDDLEWARE:
            if ext not in exts:
                continue
            for hit in _collect(pattern, text, rel,
                                lambda m: {"kind": "middleware", "detail": "USE %s" % m.group(2)}):
                hit["framework"] = framework
                found.append(hit)

        for framework, exts, pattern, make in ROUTES:
            if ext not in exts:
                continue
            for hit in _collect(pattern, text, rel,
                                lambda m, mk=make: {"kind": "http", "detail": mk(m)}):
                hit["framework"] = framework
                found.append(hit)

        if rel.endswith("urls.py"):
            for hit in _collect(DJANGO_RE, text, rel,
                                lambda m: {"kind": "http", "detail": "PATH %s" % m.group(2)}):
                hit["framework"] = "django"
                found.append(hit)
            for match in DJANGO_INCLUDE_RE.finditer(text):
                module = match.group(2)
                included = _resolve_include(rel, module, known)
                if included:
                    found.append({"kind": "http", "framework": "django", "file": included,
                                  "line": 1, "detail": "INCLUDE %s" % module})
                else:
                    found.append({"kind": "http", "framework": "django", "file": rel,
                                  "line": _line_of(text, match.start()),
                                  "detail": "INCLUDE %s (unresolved)" % module})

        if ENTRY_FILE_RE.search(rel):
            for pattern in PUBLIC_EXPORT_RES:
                match = pattern.search(text)
                if not match:
                    continue
                name = match.group(1) if match.groups() else "*"
                found.append({"kind": "public-api", "framework": "module", "file": rel,
                              "line": _line_of(text, match.start()),
                              "detail": "EXPORT %s" % name})
                break

        if NEXT_APP_PATH.search(rel):
            for hit in _collect(NEXT_APP_RE, text, rel,
                                lambda m: {"kind": "http", "detail": m.group(1)}):
                hit["framework"] = "next"
                found.append(hit)
        elif NEXT_PAGES_PATH.search(rel):
            found.append({"kind": "http", "framework": "next", "file": rel, "line": 1,
                          "detail": "API ROUTE"})

        if ext == ".json" and rel.endswith("package.json"):
            try:
                pkg = json.loads(text)
            except ValueError:
                pkg = {}
            bin_field = pkg.get("bin")
            if isinstance(bin_field, str):
                found.append({"kind": "cli", "framework": "node", "file": rel, "line": 1,
                              "detail": pkg.get("name", "bin")})
            elif isinstance(bin_field, dict):
                for name in sorted(bin_field):
                    found.append({"kind": "cli", "framework": "node", "file": rel,
                                  "line": 1, "detail": name})

        shebang = text[:200]
        if ext in JS_EXT and CLIENT_JS_RE.search(shebang):
            found.append({"kind": "cli", "framework": "node", "file": rel, "line": 1,
                          "detail": "shebang node"})
        if ext in PY_EXT:
            if CLIENT_PY_RE.search(shebang):
                found.append({"kind": "cli", "framework": "python", "file": rel,
                              "line": 1, "detail": "shebang python"})
            for hit in _collect(PY_MAIN_RE, text, rel, lambda m: {"kind": "cli", "detail": "__main__"}):
                hit["framework"] = "python"
                found.append(hit)
            for hit in _collect(CLICK_CMD_RE, text, rel,
                                lambda m: {"kind": "cli", "detail": "click/typer command"}):
                hit["framework"] = "python"
                found.append(hit)

        for pattern, label in CONSUMER_RES:
            for hit in _collect(pattern, text, rel, lambda m, l=label: {"kind": "consumer", "detail": l}):
                found.append(hit)
        for pattern, label in CRON_RES:
            for hit in _collect(pattern, text, rel, lambda m, l=label: {"kind": "cron", "detail": l}):
                found.append(hit)

    seen = set()
    unique = []
    for e in found:
        key = (e["kind"], e["file"], e["line"], e["detail"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(e)
    unique.sort(key=lambda e: (e["file"], e["line"]))
    return unique


def entrypoint_counts(entrypoints):
    counts = {"http": 0, "cli": 0, "cron": 0, "consumer": 0,
              "middleware": 0, "public-api": 0}
    for e in entrypoints:
        if e["kind"] in counts:
            counts[e["kind"]] += 1
    return counts
