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

JVM_EXTS = {".java", ".kt", ".kts"}

# Java: `import a.b.C;`, `import a.b.*;`, `import static a.b.C.member;`.
JAVA_IMPORT_RE = re.compile(
    r"^[ \t]*import[ \t]+(?:(static)[ \t]+)?([\w.]+?)(\.\*)?[ \t\r]*;", re.M)
# Kotlin: `import a.b.C`, `import a.b.*`, `import a.b.C as D`, optional `;`.
KOTLIN_IMPORT_RE = re.compile(
    r"^[ \t]*import[ \t]+([\w.]+?)(\.\*)?(?:[ \t]+as[ \t]+\w+)?[ \t\r]*;?[ \t\r]*(?=//|$)",
    re.M)

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


def _jvm_index(known):
    """Map every trailing path of a JVM source file to that file.

    Java and Kotlin compile from a source root (`src/main/java`, `src/main/kotlin`,
    `app/src/main/java`) that the import never names, so `com.acme.Foo` has to
    resolve as a suffix of a scanned path. Longest-prefix lookups are exact
    matches in this table; nothing outside the scanned set can be produced.
    """
    index = {}
    for rel in known:
        if posixpath.splitext(rel)[1] not in JVM_EXTS:
            continue
        parts = rel.split("/")
        for start in range(len(parts)):
            index.setdefault("/".join(parts[start:]), []).append(rel)
    return index


def _jvm_lookup(index, suffix):
    """Deterministic pick when two scanned roots share a package path."""
    hits = index.get(suffix)
    if not hits:
        return None
    return min(hits, key=lambda path: (path.count("/"), path))


def _resolve_java(spec, index, static=False):
    """`a.b.C` -> `<source root>/a/b/C.java`. A static member import resolves to
    its class: drop trailing segments until a scanned file matches."""
    parts = [p for p in spec.split(".") if p]
    if not parts:
        return None
    cuts = range(len(parts), 0, -1) if static else [len(parts)]
    for cut in cuts:
        hit = _jvm_lookup(index, "/".join(parts[:cut]) + ".java")
        if hit:
            return hit
    return None


def _resolve_kotlin(spec, index):
    """`a.b.Bar` -> `Bar.kt`, `bar.kt`, then `Bar.java` for mixed projects.

    The lowercase form covers top-level declarations imported by name
    (`import com.acme.util.clock` where `clock.kt` declares `fun clock()`).
    """
    parts = [p for p in spec.split(".") if p]
    if not parts:
        return None
    directory = "/".join(parts[:-1])
    name = parts[-1]
    stems = [name]
    if name.lower() != name:
        stems.append(name.lower())
    for stem in stems:
        path = posixpath.join(directory, stem) if directory else stem
        hit = _jvm_lookup(index, path + ".kt")
        if hit:
            return hit
    path = posixpath.join(directory, name) if directory else name
    return _jvm_lookup(index, path + ".java")


def _package_peers(known):
    """Java visibility is package-scoped: same directory is same package."""
    by_dir = {}
    for rel in known:
        if rel.endswith(".java"):
            by_dir.setdefault(posixpath.dirname(rel), set()).add(rel)
    return by_dir


def _mentions_type(text, peer):
    """Same-package access is only an edge when the peer's type name is used.

    Visibility alone would make one import lift every class in a 40-class
    package. This is proof of use, not a symbol table: a field or local of that
    type, an extends/implements clause, a static call — any occurrence counts.
    """
    name = posixpath.basename(peer)[: -len(".java")]
    if not name or name in ("package-info", "module-info"):
        return False
    return re.search(r"(?<![\w$])%s(?![\w$])" % re.escape(name), text) is not None


def build_graph(files, aliases=None):
    known = {f["rel"] for f in files}
    graph = {rel: set() for rel in known}
    jvm_index = None
    jvm_peers = None

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
        elif f["ext"] in JVM_EXTS:
            if jvm_index is None:
                jvm_index = _jvm_index(known)
            if f["ext"] == ".java":
                for match in JAVA_IMPORT_RE.finditer(text):
                    static = match.group(1) is not None
                    if match.group(3) and not static:
                        continue  # wildcard imports name no file
                    target = _resolve_java(match.group(2), jvm_index, static)
                    if target and target != rel:
                        graph[rel].add(target)
                if jvm_peers is None:
                    jvm_peers = _package_peers(known)
                for peer in jvm_peers.get(posixpath.dirname(rel), ()):
                    if peer != rel and _mentions_type(text, peer):
                        graph[rel].add(peer)
            else:
                for match in KOTLIN_IMPORT_RE.finditer(text):
                    if match.group(2):
                        continue  # star import names no file
                    target = _resolve_kotlin(match.group(1), jvm_index)
                    if target and target != rel:
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
