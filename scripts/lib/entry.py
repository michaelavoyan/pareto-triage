"""Entrypoint extraction. Regex based in M0; tree-sitter arrives in M2."""

import json
import posixpath
import re

from .lang import EXT_LANG

JS_EXT = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
PY_EXT = {".py"}
JVM_EXT = {".java", ".kt", ".kts"}
SWIFT_EXT = {".swift"}
OBJC_EXT = {".m", ".mm"}
OBJC_HEADER_EXT = {".h"}

# An entrypoint language has to carry the repo. Signal-iOS has 22 bundled Python
# files (39 CLI entrypoints) beside 705k lines of Swift with no entrypoint at
# all; the gate passed on the helpers while the app itself contributed nothing.
# Five percent is a floor, not a claim about any particular repo.
ENTRY_LANGUAGE_FLOOR = 0.05

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
    (re.compile(r"@(?:app\.task|shared_task)\b"), "celery task"),
    (re.compile(r"new\s+Consumer\s*\("), "kafka consumer"),
]

# `.consume(` alone is not a queue signal. On Signal-Android every remaining
# consumer seed was a Compose pointer-input `consume()` in gesture code, which
# is a no-op in the UI, not a workload boundary. It counts only when the
# receiver names a queue or the line does: otherwise the seed is invented and
# every reach number behind it is inflated.
CONSUME_RE = re.compile(r"\.[ \t]*consume[ \t]*\(")
CONSUME_RECEIVER_RE = re.compile(r"consumer|queue|subscription", re.I)
CONSUME_LINE_RE = re.compile(r"topic|queueName|partition", re.I)

# Android components are instantiated by the framework, so their files are
# entrypoints even though nothing in the codebase calls them. Exact base names
# only: `Activity` is Android's, but a `class Foo extends Activity` in some
# other framework is indistinguishable here, and a wrong seed outranks a
# missing one.
ANDROID_COMPONENTS = {
    "Activity": ("ui", "ACTIVITY"),
    "AppCompatActivity": ("ui", "ACTIVITY"),
    "ComponentActivity": ("ui", "ACTIVITY"),
    "FragmentActivity": ("ui", "ACTIVITY"),
    "Fragment": ("ui", "ACTIVITY"),
    "Service": ("background", "SERVICE"),
    "IntentService": ("background", "SERVICE"),
    "JobService": ("background", "SERVICE"),
    "Worker": ("background", "WORKER"),
    "BroadcastReceiver": ("background", "RECEIVER"),
    "ContentProvider": ("background", "PROVIDER"),
    "Application": ("app", "APPLICATION"),
}

JVM_CLASS_RE = re.compile(
    r"^[ \t]*(?:(?:public|protected|private|internal|abstract|open|final|sealed"
    r"|data|static|strictfp|inline|value|inner|expect|actual)[ \t]+)*"
    r"class[ \t]+([A-Za-z_$][\w$]*)",
    re.M)

# Rx `.subscribe(` is not a queue entrypoint: it is how an in-process stream is
# consumed, and on Signal-Android every one of the 113 "consumers" was an
# internal subscription. Count it only when the path names a worker or service
# and the same line schedules on Schedulers.io. A false seed is worse than a
# missing one, so anything less specific stays out.
RX_SUBSCRIBE_RE = re.compile(r"\.subscribe\s*\(")
RX_WORKER_PATH_RE = re.compile(r"worker|service", re.I)
RX_IO_RE = re.compile(r"Schedulers\.io")

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

JAVA_MAIN_RE = re.compile(r"\bpublic\s+static\s+void\s+main\s*\(")
KOTLIN_MAIN_RE = re.compile(r"^[ \t]*(?:(?:public|private|internal|external)[ \t]+)*fun[ \t]+main[ \t]*\(", re.M)

# Spring and JAX-RS route annotations. `@GET`/`@POST` carry no path of their own;
# JAX-RS puts it in a separate `@Path`, which is not joined here.
HTTP_ANNOTATION_RE = re.compile(
    r"@(GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|RequestMapping)\b"
    r"(?:[ \t]*\(([^()\n]*(?:\([^()\n]*\)[^()\n]*)*)\))?")
JAXRS_ANNOTATION_RE = re.compile(r"@(GET|POST)\b")

SPRING_VERBS = {
    "GetMapping": "GET", "PostMapping": "POST", "PutMapping": "PUT",
    "DeleteMapping": "DELETE", "PatchMapping": "PATCH", "RequestMapping": "ANY",
}


def _spring_detail(annotation, args):
    """`GET /users`; the verb alone when the annotation names no path."""
    verb = SPRING_VERBS[annotation]
    if annotation == "RequestMapping":
        named = re.search(r"method\s*=\s*(?:RequestMethod\.)?([A-Z]+)", args or "")
        if named:
            verb = named.group(1)
    quoted = re.search(r"['\"]([^'\"]+)['\"]", args or "")
    return "%s %s" % (verb, quoted.group(1)) if quoted else verb


def _line_of(text, index):
    return text.count("\n", 0, index) + 1


def _line_at(text, index):
    """The whole line around `index`, used when a call's meaning is on it."""
    start = text.rfind("\n", 0, index) + 1
    end = text.find("\n", index)
    return text[start:] if end < 0 else text[start:end]


def _receiver_before(text, index):
    """The identifier immediately left of `text[index]`, or "".

    Done by hand: a regex that captures the receiver and then requires the call
    backtracks quadratically over long chained expressions, and a 10k-file repo
    pays for it on every line.
    """
    end = index
    while end > 0 and text[end - 1] in " \t":
        end -= 1
    start = end
    while start > 0 and (text[start - 1].isalnum() or text[start - 1] in "_$"):
        start -= 1
    return text[start:end]


def _class_header(text, start):
    """Text after a class name up to the body, so a wrapped header still counts."""
    end = start
    limit = min(len(text), start + 400)
    while end < limit:
        if text[end] in "{;}" or text.startswith("\n\n", end):
            break
        end += 1
    return text[start:end]


def _top_level_colon(header):
    depth = 0
    for index, char in enumerate(header):
        if char in "([<{":
            depth += 1
        elif char in ")]>}":
            depth = max(depth - 1, 0)
        elif char == ":" and depth == 0:
            return index
    return -1


def _split_top_level(header):
    """Split a supertype list on commas that are not inside generics or args."""
    parts = []
    token = ""
    depth = 0
    for char in header:
        if char in "([<{":
            depth += 1
        elif char in ")]>}":
            depth = max(depth - 1, 0)
        if char == "," and depth == 0:
            parts.append(token)
            token = ""
            continue
        token += char
    parts.append(token)
    return parts


def _android_supertypes(header, kotlin):
    """Base type names named in a class header. Java: extends/implements.

    Kotlin has no keyword, so the list after the first top-level `:` is the
    supertypes — constructor parameters are inside brackets, which the depth
    count skips.
    """
    if kotlin:
        index = _top_level_colon(header)
        if index < 0:
            return []
        expressions = _split_top_level(header[index + 1:])
    else:
        expressions = []
        for chunk in re.split(r"\b(?:extends|implements)\b", header)[1:]:
            expressions.extend(_split_top_level(chunk))

    names = []
    for expression in expressions:
        # `Fragment<Foo>` and `IntentService("x")` name Fragment and IntentService.
        name = re.split(r"[<(]", expression.strip(), 1)[0]
        name = name.split(".")[-1].strip()
        if name:
            names.append(name)
    return names


# How many class-to-base edges a project base chain may cross before it stops
# counting. Deep chains are common (`ConversationActivity -> PassphraseRequired
# Activity -> BaseActivity -> AppCompatActivity`); an unbounded walk would let a
# cycle invent a root, so the limit is explicit.
ANDROID_MAX_HOPS = 4


def _jvm_type_table(files):
    """Simple declaration name -> every file/line that declares it.

    Only classes are indexed: an interface cannot be a component, and following
    one would add edges without a framework instantiation at the end. The table
    is built from the scanned set alone, so an ancestor outside the repo stays
    unresolved rather than being guessed from its name.
    """
    table = {}
    for f in files:
        if f["ext"] not in JVM_EXT:
            continue
        kotlin = f["ext"] in (".kt", ".kts")
        text = f["text"]
        for match in JVM_CLASS_RE.finditer(text):
            header = _class_header(text, match.end())
            table.setdefault(match.group(1), []).append({
                "file": f["rel"],
                "line": _line_of(text, match.start(1)),
                "supertypes": _android_supertypes(header, kotlin),
            })
    return table


def _pick_declaration(records):
    """Deterministic pick when one simple name is declared in several files.

    The shallowest path wins, then the lexicographically first, then the first
    declaration in that file. A scan cannot know which one a build would pick,
    so this is a rule, not a claim about the module graph.
    """
    return min(records, key=lambda d: (d["file"].count("/"), d["file"], d["line"]))


def _component_through(supertypes, table, components, max_hops=ANDROID_MAX_HOPS):
    """Walk the parsed ancestor chain to a framework component base.

    Direct supertypes are hop 1. A name that is neither a component nor a
    scanned declaration is a dead branch: the chain stays unresolved and the
    class is not seeded, because a wrong seed outranks a missing one. The same
    walk serves Android, Swift, and Objective-C; only `components` differs.
    """
    frontier = sorted(set(supertypes))
    seen = set(frontier)
    for _ in range(max_hops):
        for name in frontier:
            component = components.get(name)
            if component is not None:
                return component
        nxt = set()
        for name in frontier:
            records = table.get(name) or []
            if not records:
                continue
            record = _pick_declaration(records)
            for base in record["supertypes"]:
                if base not in seen:
                    seen.add(base)
                    nxt.add(base)
        frontier = sorted(nxt)
        if not frontier:
            return None
    return None


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


def _strip_comments(text):
    """Comments declare nothing: a commented-out class must not seed a file.

    Block comments are replaced by their newlines so line numbers stay true.
    """
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    return re.sub(r"(?m)//.*$", "", text)


def _swift_supertypes(header):
    """The inheritance list after the first top-level `:`.

    Generic parameters and constructor arguments are inside brackets, which the
    depth count skips; `where` clauses are cut off the last name they follow.
    """
    index = _top_level_colon(header)
    if index < 0:
        return []
    names = []
    for expression in _split_top_level(header[index + 1:]):
        token = re.split(r"[<(]", expression.strip(), 1)[0].strip()
        token = token.split()[0] if token else ""
        name = token.split(".")[-1]
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            names.append(name)
    return names


def _swift_type_table(files):
    """Simple class name -> every declaration, with its parsed supertypes."""
    table = {}
    for f in files:
        if f["ext"] not in SWIFT_EXT:
            continue
        text = _strip_comments(f["text"])
        for match in SWIFT_CLASS_RE.finditer(text):
            table.setdefault(match.group(1), []).append({
                "file": f["rel"],
                "line": _line_of(text, match.start(1)),
                "supertypes": _swift_supertypes(_class_header(text, match.end())),
            })
    return table


def _objc_impl_index(files):
    """`X.h` -> `X.m`/`X.mm`: the declaration and its body are one file."""
    impl = {}
    for f in files:
        stem, ext = posixpath.splitext(f["rel"])
        if ext in OBJC_EXT:
            impl.setdefault(stem + ".h", f["rel"])
    return impl


def _objc_type_table(files):
    """`@interface` declarations, pointed at the implementation that holds code.

    A header with no scanned implementation keeps the header as its file; the
    entrypoint pass skips it, because a header body is not something to rank.
    """
    impl_of = _objc_impl_index(files)
    table = {}
    for f in files:
        if f["ext"] not in OBJC_EXT | OBJC_HEADER_EXT:
            continue
        text = _strip_comments(f["text"])
        for match in OBJC_INTERFACE_RE.finditer(text):
            header = _class_header(text, match.end())
            supertypes = [match.group(2)] if match.group(2) else []
            for block in OBJC_PROTOCOL_RE.findall(header):
                for name in block.split(","):
                    name = name.strip().split()[-1] if name.strip() else ""
                    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                        supertypes.append(name)
            table.setdefault(match.group(1), []).append({
                "file": impl_of.get(f["rel"], f["rel"]),
                "line": _line_of(text, match.start(1)),
                "supertypes": supertypes,
            })
    return table


def _ios_entrypoints(files):
    """Swift and Objective-C entrypoints, reusing the Android chain walk.

    `@main`, `@UIApplicationMain`, and `UIApplicationMain(` are the process
    entry (ui, `MAIN`). A class conforming to `UIApplicationDelegate`,
    `AppDelegate`, or `SceneDelegate` is the app (app, `APPDELEGATE X`). A
    `UIViewController` or `UIView` subclass, directly or through a project base
    up to four hops, is UI (`VIEWCONTROLLER X`). Delegate conformance is read
    from the class's own declaration only: Swift does not inherit it.

    An ObjC `@interface` lives in a header, so the entrypoint is the scanned
    implementation. @IBAction handlers are deliberately not seeded: the
    controller file is already the entrypoint, and seeding each handler would
    multiply one file's seeds for no extra reach.
    """
    found = []
    for f in files:
        if f["ext"] not in SWIFT_EXT and f["ext"] not in OBJC_EXT:
            continue
        text = _strip_comments(f["text"])
        if f["ext"] in SWIFT_EXT:
            for match in SWIFT_MAIN_ATTR_RE.finditer(text):
                found.append({"kind": "ui", "framework": "ios", "file": f["rel"],
                              "line": _line_of(text, match.start()), "detail": "MAIN"})
        for match in UIKIT_MAIN_CALL_RE.finditer(text):
            found.append({"kind": "ui", "framework": "ios", "file": f["rel"],
                          "line": _line_of(text, match.start()), "detail": "MAIN"})

    for framework, table in (("swift", _swift_type_table(files)),
                             ("objc", _objc_type_table(files))):
        for name in sorted(table):
            for record in table[name]:
                if record["file"].endswith(".h"):
                    continue
                if any(base in IOS_APP_DELEGATES for base in record["supertypes"]):
                    found.append({"kind": "app", "framework": framework,
                                  "file": record["file"], "line": record["line"],
                                  "detail": "APPDELEGATE %s" % name})
                component = _component_through(
                    record["supertypes"], table, IOS_VIEW_BASES)
                if component is None:
                    continue
                kind, label = component
                found.append({"kind": kind, "framework": framework,
                              "file": record["file"], "line": record["line"],
                              "detail": "%s %s" % (label, name)})
    return found


def filter_entrypoints_by_language(entrypoints, supported):
    """Drop entrypoints whose language supplies under 5% of supported lines.

    A bundled helper language can supply seeds for a repo it does not carry.
    Returns (kept, ignored), where each `ignored` record names the language,
    how many entrypoints it supplied, its non-blank lines, and its share.

    An entrypoint on a file with no source language (a `package.json` `bin`)
    names no lines of its own, so the share test does not apply to it.
    """
    total = sum(entry["loc"] for entry in supported)
    shares = {entry["lang"]: (entry["loc"] / total if total else 0.0) for entry in supported}
    kept = []
    ignored = {}
    for entry in entrypoints:
        lang = EXT_LANG.get(posixpath.splitext(entry["file"])[1].lower())
        if lang is None or shares.get(lang, 0.0) >= ENTRY_LANGUAGE_FLOOR:
            kept.append(entry)
            continue
        slot = ignored.setdefault(lang, {
            "lang": lang,
            "entrypoints": 0,
            "loc": next((e["loc"] for e in supported if e["lang"] == lang), 0),
            "share": shares.get(lang, 0.0),
        })
        slot["entrypoints"] += 1
    return kept, [ignored[lang] for lang in sorted(ignored)]


def extract_entrypoints(files):
    from .walk import is_test_path

    found = []
    files = [f for f in files if not is_test_path(f["rel"])]
    known = _known_paths(files)
    type_table = _jvm_type_table(files)

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

        if ext in JVM_EXT:
            for hit in _collect(JAVA_MAIN_RE, text, rel, lambda m: {"kind": "cli", "detail": "main"}):
                hit["framework"] = "java"
                found.append(hit)
            for hit in _collect(KOTLIN_MAIN_RE, text, rel, lambda m: {"kind": "cli", "detail": "main"}):
                hit["framework"] = "kotlin"
                found.append(hit)
            for match in HTTP_ANNOTATION_RE.finditer(text):
                found.append({"kind": "http", "framework": "spring", "file": rel,
                              "line": _line_of(text, match.start()),
                              "detail": _spring_detail(match.group(1), match.group(2))})
            for match in JAXRS_ANNOTATION_RE.finditer(text):
                found.append({"kind": "http", "framework": "jaxrs", "file": rel,
                              "line": _line_of(text, match.start()),
                              "detail": match.group(1)})
            kotlin = ext in (".kt", ".kts")
            for match in JVM_CLASS_RE.finditer(text):
                header = _class_header(text, match.end())
                component = _component_through(
                    _android_supertypes(header, kotlin), type_table, ANDROID_COMPONENTS)
                if component is None:
                    continue
                kind, label = component
                found.append({"kind": kind, "framework": "android", "file": rel,
                              "line": _line_of(text, match.start(1)),
                              "detail": "%s %s" % (label, match.group(1))})

        for pattern, label in CONSUMER_RES:
            for hit in _collect(pattern, text, rel, lambda m, l=label: {"kind": "consumer", "detail": l}):
                found.append(hit)
        for match in CONSUME_RE.finditer(text):
            if not (CONSUME_RECEIVER_RE.search(_receiver_before(text, match.start()))
                    or CONSUME_LINE_RE.search(_line_at(text, match.start()))):
                continue
            found.append({"kind": "consumer", "file": rel,
                          "line": _line_of(text, match.start()), "detail": "consume"})
        if RX_WORKER_PATH_RE.search(rel):
            for line_no, line in enumerate(text.splitlines(), start=1):
                if RX_SUBSCRIBE_RE.search(line) and RX_IO_RE.search(line):
                    found.append({"kind": "consumer", "framework": "rx", "file": rel,
                                  "line": line_no, "detail": "subscribe on Schedulers.io"})
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
              "middleware": 0, "public-api": 0,
              "ui": 0, "background": 0, "app": 0}
    for e in entrypoints:
        if e["kind"] in counts:
            counts[e["kind"]] += 1
    return counts
