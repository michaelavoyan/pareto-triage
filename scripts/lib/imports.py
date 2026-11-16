"""Import graph and file-level reachability.

`reach` answers one question: how close is this file to something the outside
world can call? Seeds come from entrypoint kind; each import hop costs one
level; nothing reachable is 1. This is file-level, not symbol-level — the
documented degraded mode in references/entrypoints.md.
"""

import posixpath
import re

SEED_BY_KIND = {
    "http": 5,
    "middleware": 4,
    "consumer": 4,
    "cron": 4,
    "cli": 3,
    "public-api": 3,
}

REACH_FLOOR = 2

# Both relative and bare specifiers are captured: a bare one may resolve through
# tsconfig paths or a workspace name, and is dropped when it does not.
JS_IMPORT_RES = [
    re.compile(r"""\bfrom\s+['"]([^'"]+)['"]"""),
    re.compile(r"""\brequire\(\s*['"]([^'"]+)['"]\s*\)"""),
    re.compile(r"""\bimport\(\s*['"]([^'"]+)['"]\s*\)"""),
    # Side-effect imports: `import './setup'` pulls the module in for its effects.
    re.compile(r"""^\s*import\s+['"]([^'"]+)['"]""", re.M),
]
PY_FROM_RE = re.compile(r"^\s*from\s+(\.+)([\w.]*)\s+import\b", re.M)
PY_IMPORT_RE = re.compile(r"^\s*import\s+([\w.]+)", re.M)

JS_EXTS = [".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json"]


def _js_candidates(base):
    return ([base]
            + [base + ext for ext in JS_EXTS]
            + [posixpath.join(base, "index" + ext) for ext in JS_EXTS[:6]])


def _match_alias(spec, pattern):
    """Return the wildcard text matched by `pattern`, or None."""
    if "*" not in pattern:
        return "" if spec == pattern else None
    prefix, suffix = pattern.split("*", 1)
    if not spec.startswith(prefix) or not spec.endswith(suffix):
        return None
    if len(spec) < len(prefix) + len(suffix):
        return None
    return spec[len(prefix):len(spec) - len(suffix)]


def _resolve_bare(spec, known, aliases):
    """Resolve a non-relative specifier through tsconfig paths or workspace names."""
    if not aliases:
        return None

    for pattern, targets in aliases.get("paths", []):
        wildcard = _match_alias(spec, pattern)
        if wildcard is None:
            continue
        for target in targets:
            base = posixpath.normpath(posixpath.join(aliases.get("base_url") or "",
                                                     target.replace("*", wildcard)))
            for candidate in _js_candidates(base):
                if candidate in known:
                    return candidate

    for name, directory in aliases.get("packages", {}).items():
        if spec != name and not spec.startswith(name + "/"):
            continue
        rest = spec[len(name) + 1:] if spec != name else ""
        base = posixpath.normpath(posixpath.join(directory, rest)) if rest else directory
        for candidate in _js_candidates(base) + _js_candidates(posixpath.join(directory, "src", rest or "index")):
            if candidate in known:
                return candidate
    return None


def _resolve_js(rel, spec, known, aliases=None):
    if spec.startswith("."):
        base = posixpath.normpath(posixpath.join(posixpath.dirname(rel), spec))
        for candidate in _js_candidates(base):
            if candidate in known:
                return candidate
        return None
    return _resolve_bare(spec, known, aliases)


def _resolve_py(rel, dots, module, known):
    parts = [p for p in module.split(".") if p]
    if dots:
        base = posixpath.dirname(rel)
        for _ in range(len(dots) - 1):
            base = posixpath.dirname(base)
        candidates = [posixpath.join(base, *parts) + ".py"]
        if parts:
            candidates.append(posixpath.join(base, *parts, "__init__.py"))
        for candidate in candidates:
            if candidate in known:
                return candidate
        return None

    if not parts:
        return None
    base = posixpath.dirname(rel)
    while True:
        candidate = posixpath.join(base, *parts) + ".py"
        init = posixpath.join(base, *parts, "__init__.py")
        if candidate in known:
            return candidate
        if init in known:
            return init
        if base in ("", "."):
            return None
        base = posixpath.dirname(base)
        if base == "":
            base = "."


def build_graph(files, aliases=None):
    known = {f["rel"] for f in files}
    graph = {rel: set() for rel in known}

    for f in files:
        rel = f["rel"]
        text = f["text"]
        if f["ext"] in JS_EXTS:
            for pattern in JS_IMPORT_RES:
                for match in pattern.finditer(text):
                    target = _resolve_js(rel, match.group(1), known, aliases)
                    if target:
                        graph[rel].add(target)
        elif f["ext"] == ".py":
            for match in PY_FROM_RE.finditer(text):
                target = _resolve_py(rel, match.group(1), match.group(2), known)
                if target:
                    graph[rel].add(target)
            for match in PY_IMPORT_RE.finditer(text):
                target = _resolve_py(rel, "", match.group(1), known)
                if target:
                    graph[rel].add(target)

    return graph


def read_aliases(root):
    """tsconfig paths plus workspace package names. Missing or malformed is empty."""
    import json
    from pathlib import Path

    aliases = {"base_url": None, "paths": [], "packages": {}}
    root = Path(root)

    tsconfig = root / "tsconfig.json"
    if tsconfig.exists():
        text = tsconfig.read_text(encoding="utf-8", errors="replace")
        text = re.sub(r"//[^\n]*", "", text)
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        text = re.sub(r",(\s*[}\]])", r"\1", text)
        try:
            data = json.loads(text)
        except ValueError:
            data = {}
        options = data.get("compilerOptions") or {}
        base_url = options.get("baseUrl")
        if isinstance(base_url, str):
            aliases["base_url"] = posixpath.normpath(base_url)
        paths = options.get("paths") or {}
        if isinstance(paths, dict):
            for pattern in sorted(paths):
                targets = paths[pattern]
                if isinstance(targets, list) and all(isinstance(t, str) for t in targets):
                    aliases["paths"].append((pattern, targets))

    manifest = root / "package.json"
    if manifest.exists():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8", errors="replace"))
        except ValueError:
            data = {}
        workspaces = data.get("workspaces")
        if isinstance(workspaces, dict):
            workspaces = workspaces.get("packages")
        if isinstance(workspaces, list):
            for pattern in sorted(w for w in workspaces if isinstance(w, str)):
                for child in sorted(root.glob(pattern)):
                    name = _package_name(child)
                    if name:
                        aliases["packages"][name] = child.relative_to(root).as_posix()
    return aliases


def _package_name(directory):
    manifest = directory / "package.json"
    try:
        import json
        data = json.loads(manifest.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return None
    name = data.get("name")
    return name if isinstance(name, str) else None


def entry_paths(files, entry_files, max_depth=3, aliases=None):
    """Shortest import path from an entrypoint file to every reachable file.

    File-level, matching compute_reach. Deterministic: ties break on sorted order.
    """
    graph = build_graph(files, aliases)
    paths = {rel: [rel] for rel in entry_files}
    frontier = sorted(entry_files)

    for _ in range(max_depth):
        nxt = []
        for source in frontier:
            for target in sorted(graph.get(source, ())):
                if target in paths:
                    continue
                paths[target] = paths[source] + [target]
                nxt.append(target)
        frontier = sorted(nxt)

    return paths


def seeds_from_entrypoints(entrypoints):
    """file -> best seed. A file can be several things; the closest wins."""
    seeds = {}
    for entry in entrypoints:
        seed = SEED_BY_KIND.get(entry.get("kind"), 1)
        current = seeds.get(entry["file"], 0)
        if seed > current:
            seeds[entry["file"]] = seed
    return seeds


def compute_reach(files, entry_files, max_depth=3, seeds=None, skipped=None, aliases=None):
    """Return (reach_for_file, meta)."""
    if seeds is None:
        seeds = {rel: SEED_BY_KIND["http"] for rel in entry_files}

    graph = build_graph(files, aliases)
    best = dict(seeds)
    frontier = sorted(seeds)

    for _ in range(max_depth):
        nxt = []
        for source in frontier:
            decayed = max(best[source] - 1, REACH_FLOOR)
            for target in sorted(graph.get(source, ())):
                if decayed > best.get(target, 0):
                    best[target] = decayed
                    nxt.append(target)
        frontier = sorted(set(nxt))

    unreadable = set(skipped or ())

    def reach(rel):
        if rel in unreadable:
            return 0
        return best.get(rel, 1)

    meta = {
        "mode": "file-level",
        "max_depth": max_depth,
        "entry_files": sorted(entry_files),
        "seeds": {rel: best.get(rel) for rel in sorted(seeds)},
        "resolved_edges": sum(len(v) for v in graph.values()),
        "reachable_files": len(best),
    }
    return reach, meta
