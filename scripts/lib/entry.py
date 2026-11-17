"""Entrypoint extraction. Regex based in M0; tree-sitter arrives in M2."""

import json
import posixpath
import re

JS_EXT = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
PY_EXT = {".py"}
JVM_EXT = {".java", ".kt", ".kts"}

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
    from .walk import is_test_path

    found = []
    files = [f for f in files if not is_test_path(f["rel"])]
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
                for base in _android_supertypes(header, kotlin):
                    component = ANDROID_COMPONENTS.get(base)
                    if component is None:
                        continue
                    kind, label = component
                    found.append({"kind": kind, "framework": "android", "file": rel,
                                  "line": _line_of(text, match.start(1)),
                                  "detail": "%s %s" % (label, match.group(1))})
                    break

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
