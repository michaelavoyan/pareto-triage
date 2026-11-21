"""Built-in defect rules.

Only rules whose presence is certain at a line belong here. Judgment about
impact lives in the rubric; this module only answers "is this construct here".

Every evidence string is copied from the source so the hallucination guard in
schema.py passes by construction.
"""

import ast
import hashlib
import re

JS_EXT = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
PY_EXT = {".py"}
JVM_EXT = {".java", ".kt", ".kts"}

META = {
    # rule id: (taxonomy, blast, silence, message)
    "py-eval": ("code-injection", 5, 2,
                "eval()/exec() runs whatever its argument contains"),
    "py-os-system": ("command-injection", 5, 2,
                     "os.system() passes a string to a shell"),
    "py-shell-true": ("command-injection", 5, 2,
                      "subprocess called with shell=True and no argument escaping"),
    "py-pickle": ("unsafe-deserialization", 5, 3,
                  "unpickling arbitrary bytes constructs arbitrary objects"),
    "py-yaml-load": ("unsafe-deserialization", 5, 3,
                     "yaml.load without SafeLoader can construct arbitrary objects"),
    "py-sql-interp": ("sql-injection", 5, 2,
                      "SQL built by string interpolation carries its input into the query"),
    "py-verify-false": ("tls-verification-disabled", 5, 3,
                        "certificate verification disabled"),
    "py-bare-except": ("bare-except", 4, 3,
                       "bare except swallows every error, including interrupts"),
    "py-mutable-default": ("mutable-default-arg", 3, 3,
                           "mutable default is shared across calls"),
    "py-debug-true": ("debug-mode-enabled", 4, 2,
                      "debug mode enabled in application startup"),
    "js-eval": ("code-injection", 5, 2,
                "eval() runs whatever its argument contains"),
    "js-new-function": ("code-injection", 5, 2,
                        "new Function() compiles a string into code"),
    "js-exec-interp": ("command-injection", 5, 2,
                       "shell command built from an interpolated template"),
    "js-tls-off": ("tls-verification-disabled", 5, 3,
                   "rejectUnauthorized: false disables certificate checks"),
    "js-secret-aws": ("hardcoded-secret", 5, 3,
                      "AWS access key committed to source"),
    "js-secret-pem": ("hardcoded-secret", 5, 3,
                      "private key committed to source"),
    "js-secret-stripe": ("hardcoded-secret", 5, 3,
                         "live Stripe key committed to source"),
    "js-dangerous-html": ("xss", 5, 1,
                          "dangerouslySetInnerHTML renders unescaped markup"),
    "jvm-exec-injection": ("command-injection", 5, 2,
                           "process argument built by string concatenation"),
    "jvm-sql-injection": ("sql-injection", 5, 2,
                          "SQL built by string concatenation carries its input into the query"),
    "jvm-weak-hash": ("weak-hash", 3, 3,
                      "MD5 and SHA-1 are broken for collision resistance"),
    "jvm-object-input-stream": ("unsafe-deserialization", 5, 3,
                                "ObjectInputStream turns its input into arbitrary objects"),
    "py-secret-aws": ("hardcoded-secret", 5, 3,
                      "AWS access key committed to source"),
    "py-secret-pem": ("hardcoded-secret", 5, 3,
                      "private key committed to source"),
    "py-secret-stripe": ("hardcoded-secret", 5, 3,
                         "live Stripe key committed to source"),
    "cfg-secret-generic": ("hardcoded-secret", 4, 3,
                           "credential assigned a literal value in a config file"),
}

PY_SAFE_LOADERS = {"SafeLoader", "CSafeLoader", "FullLoader", "BaseLoader"}

# Secrets live in .env, YAML, JSON, Terraform, and INI far more often than in
# source. Code rules are meaningless in those files; secret rules are not.
SECRET_EXTS = {".yaml", ".yml", ".json", ".tf", ".tfvars", ".ini", ".properties",
               ".toml", ".cfg", ".conf"}


def is_config_secret_file(rel, ext):
    """True for a file only the config-secret rules read.

    `.env` carries no extension, and `.env.local` carries an unrelated one, so
    the basename is the signal for both. Source files are deliberately not
    included: their secret rules are not narrowed to committed files.
    """
    return ext in SECRET_EXTS or rel.rsplit("/", 1)[-1].startswith(".env")


SECRET_PATTERNS = [
    ("py-secret-aws", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("py-secret-pem", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("py-secret-stripe", re.compile(r"\bsk_live_[0-9A-Za-z]{10,}\b")),
]

CONFIG_SECRETS = [
    ("py-secret-aws", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("py-secret-pem", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("py-secret-stripe", re.compile(r"\bsk_live_[0-9A-Za-z]{10,}\b")),
    ("cfg-secret-generic",
     re.compile(r"(?i)^[ \t]*[{,]?[ \t]*[\"']?[\w.-]*(password|passwd|pwd|secret|token|api[_-]?key|"
                r"access[_-]?key|client[_-]?secret)[\w.-]*[ \t]*[:=][ \t]*"
                r"['\"]?[^'\"\s#]{6,}", re.M)),
]

# Which rules a file extension can reach. The ids are the ones META defines, so
# a report can name the detectors that ran instead of only their count. This
# table must mirror the branches in detect_defects below: coverage that claims a
# rule ran where none did is the failure this module exists to prevent.
PY_RULE_IDS = tuple(sorted(rule for rule in META if rule.startswith("py-")))
JVM_RULE_IDS = (
    "jvm-exec-injection", "jvm-sql-injection",
    "jvm-weak-hash", "jvm-object-input-stream",
) + tuple(rule for rule, _ in SECRET_PATTERNS)
CONFIG_RULE_IDS = tuple(rule for rule, _ in CONFIG_SECRETS)


def _line_hits(text, patterns):
    lines = text.split("\n")
    found = []
    for rule, pattern in patterns:
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            found.append((rule, line, lines[line - 1].strip()[:300]))
    return found


def _id(rule, rel, line):
    return "d_" + hashlib.sha1(("%s|%s|%d" % (rule, rel, line)).encode("utf-8")).hexdigest()[:8]


def _safe_loader(node):
    if isinstance(node, ast.Name):
        return node.id in PY_SAFE_LOADERS
    if isinstance(node, ast.Attribute):
        return node.attr in PY_SAFE_LOADERS
    return False


def _is_interpolated(node):
    if isinstance(node, ast.JoinedStr):
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
        return True
    return False


def _py_defects(text):
    """Return [(rule, line, evidence)] or None when the file does not parse."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None

    lines = text.split("\n")
    found = []

    def source_of(node):
        segment = ast.get_source_segment(text, node) or lines[node.lineno - 1]
        return segment.strip()[:300]

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else None
            attr = func.attr if isinstance(func, ast.Attribute) else None
            base = func.value.id if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) else None

            if name in ("eval", "exec"):
                found.append(("py-eval", node.lineno, source_of(node)))
            if base == "os" and attr == "system":
                found.append(("py-os-system", node.lineno, source_of(node)))
            if base in ("pickle", "cPickle", "dill") and attr in ("load", "loads"):
                found.append(("py-pickle", node.lineno, source_of(node)))
            if base == "yaml" and attr == "load":
                if not any(kw.arg == "Loader" and _safe_loader(kw.value) for kw in node.keywords):
                    found.append(("py-yaml-load", node.lineno, source_of(node)))
            if attr in ("execute", "executemany") and node.args and _is_interpolated(node.args[0]):
                found.append(("py-sql-interp", node.lineno, source_of(node)))

            for keyword in node.keywords:
                if keyword.arg == "shell" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                    found.append(("py-shell-true", node.lineno, source_of(node)))
                if keyword.arg == "verify" and isinstance(keyword.value, ast.Constant) and keyword.value.value is False:
                    found.append(("py-verify-false", node.lineno, source_of(node)))
                if keyword.arg == "debug" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                    found.append(("py-debug-true", node.lineno, source_of(node)))

        elif isinstance(node, ast.ExceptHandler):
            if node.type is None:
                found.append(("py-bare-except", node.lineno, lines[node.lineno - 1].strip()))

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defaults = list(node.args.defaults) + [d for d in node.args.kw_defaults if d is not None]
            for default in defaults:
                if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                    found.append(("py-mutable-default", default.lineno, source_of(default)))

    found.extend(_line_hits(text, SECRET_PATTERNS))
    return found


def _config_defects(text):
    return _line_hits(text, CONFIG_SECRETS)


JS_RULES = [
    ("js-eval", re.compile(r"\beval\s*\(")),
    ("js-new-function", re.compile(r"\bnew\s+Function\s*\(")),
    ("js-tls-off", re.compile(r"rejectUnauthorized\s*:\s*false")),
    ("js-secret-aws", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("js-secret-pem", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("js-secret-stripe", re.compile(r"\bsk_live_[0-9A-Za-z]{16,}")),
    ("js-dangerous-html", re.compile(r"dangerouslySetInnerHTML\s*=\s*\{\{")),
]

# `exec(` alone is not a shell call: a SQLite handle, a database driver, and a
# process pool all use the name. The file must import child_process, and only
# the two calls that turn a string into a shell command count. `spawn` and
# `spawnSync` are not here: without `shell: true` they take a program and an
# argument vector, so an interpolated argument is not a shell string.
CHILD_PROCESS_IMPORT = re.compile(
    r"""(?:\bfrom\s*|\brequire\s*\(\s*|\bimport\s*\(\s*)['"](?:node:)?child_process['"]""")
JS_SHELL_CALL = re.compile(r"\b(?:exec|execSync)\s*\(\s*`[^`]*\$\{")
# execFile/execFileSync take an argument vector too. They reach a shell only
# when this line asks for one, so the option must be on the matched line.
JS_EXECFILE_CALL = re.compile(r"\b(?:execFile|execFileSync)\s*\(\s*`[^`]*\$\{")
JS_SHELL_OPTION = re.compile(r"\bshell\s*:\s*true\b")

JS_RULE_IDS = tuple(rule for rule, _ in JS_RULES) + ("js-exec-interp",)


def rule_ids_for_ext(ext, rel=None):
    """Rule ids the detector can emit for one file; empty means none.

    Every branch in detect_defects has an entry here. A language whose files
    all return an empty tuple has no detector, which is reported instead of
    being read as "scanned and clean". `rel` is needed for `.env`, which has
    no extension of its own.
    """
    if ext in PY_EXT:
        return PY_RULE_IDS
    if ext in JS_EXT:
        return JS_RULE_IDS
    if ext in JVM_EXT:
        return JVM_RULE_IDS
    if ext in SECRET_EXTS or (rel is not None and is_config_secret_file(rel, ext)):
        return CONFIG_RULE_IDS
    return ()


def rule_coverage(files):
    """Per-language rule coverage for the files actually scanned.

    `files_with_rules` counts files a detector can read, not rules that fired.
    The two differ on purpose: a language can have detectors and still produce
    no finding, which is a result; a language with no detector is a blind spot,
    which is not.
    """
    from .lang import EXT_LANG

    by_lang = {}
    for f in files:
        lang = EXT_LANG.get(f["ext"])
        if lang is None:
            continue
        slot = by_lang.setdefault(
            lang, {"lang": lang, "files": 0, "files_with_rules": 0, "rules": set()})
        slot["files"] += 1
        ids = rule_ids_for_ext(f["ext"], f["rel"])
        if ids:
            slot["files_with_rules"] += 1
            slot["rules"].update(ids)

    rows = []
    for slot in by_lang.values():
        rows.append({
            "lang": slot["lang"],
            "files": slot["files"],
            "files_with_rules": slot["files_with_rules"],
            "rules": sorted(slot["rules"]),
        })
    rows.sort(key=lambda e: (-e["files"], e["lang"]))
    return {"by_language": rows}


def rule_incidence(files, findings, tracked=None):
    """Hits per rule for every rule that could run on these files.

    A zero is an exercised rule that found nothing: the detector read the
    files and the tree did not match. A rule absent from the list never ran
    because no file of its language was scanned, which is a blind spot and
    already reported as coverage. An untracked config file does not make a
    config rule "exercised" when `tracked` restricts the scan: the rule was
    never pointed at it.
    """
    applicable = set()
    for f in files:
        untracked_config = (tracked is not None and f["rel"] not in tracked
                            and is_config_secret_file(f["rel"], f["ext"]))
        if untracked_config:
            continue
        applicable.update(rule_ids_for_ext(f["ext"], f["rel"]))
    hits = {rule: 0 for rule in applicable}
    for finding in findings:
        if finding["rule"] in hits:
            hits[finding["rule"]] += 1
    return [(rule, hits[rule]) for rule in sorted(hits)]


def _js_defects(text):
    lines = text.split("\n")
    found = []

    def add(rule, match):
        line = text.count("\n", 0, match.start()) + 1
        stripped = lines[line - 1].strip()
        if stripped.startswith("//") or stripped.startswith("*"):
            return
        found.append((rule, line, stripped[:300]))

    for rule, pattern in JS_RULES:
        for match in pattern.finditer(text):
            add(rule, match)

    if CHILD_PROCESS_IMPORT.search(text):
        for match in JS_SHELL_CALL.finditer(text):
            add("js-exec-interp", match)
        for match in JS_EXECFILE_CALL.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            if JS_SHELL_OPTION.search(lines[line - 1]):
                add("js-exec-interp", match)
    return found


JVM_EXEC_CALL = re.compile(
    r"(?:\bRuntime\s*\.\s*getRuntime\s*\(\s*\)\s*\.\s*exec|\bProcessBuilder)\s*\(")
JVM_SQL_CALL = re.compile(r"\b(?:executeQuery|executeUpdate|execute)\s*\(")
JVM_SQL_VERB = re.compile(r"\b(?:SELECT|INSERT|UPDATE|DELETE|REPLACE\s+INTO)\b", re.I)
JVM_WEAK_HASH = re.compile(r"\bMessageDigest\s*\.\s*getInstance\s*\(\s*\"(?:MD5|SHA-1)\"")
JVM_OBJECT_INPUT = re.compile(r"\bnew\s+ObjectInputStream\s*\(")

# A '+' operand that is a literal or a compile-time constant. UPPER_SNAKE_CASE
# names (FILTER_SPEC, BuildConfig.ENDPOINT) are constants; a lowercase name, a
# field, a parameter, an array element, or a call is a value that can vary.
JVM_CONSTANT_OPERAND = re.compile(
    r"^(?:\"[^\"]*\"|'[^']*'|[-+]?\d+(?:\.\d+)?[fFdDlL]?|true|false|null)$")
JVM_UPPER_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _blank_noncode(text):
    """Mask comments and literal contents with spaces, keeping offsets.

    A comment becomes whitespace, so a comment-only block reads as empty. A
    string or char literal keeps its opening quote: the literal is code, and
    masking it to whitespace made a body of `""`, `"Unknown"`, or a string
    template look like an empty body.
    """
    out = []
    i = 0
    while i < len(text):
        if text[i:i + 3] == '"""':
            end = text.find('"""', i + 3)
            end = len(text) if end < 0 else end + 3
            out.append('"')
            out.append("".join(c if c == "\n" else " " for c in text[i + 1:end]))
            i = end
        elif text[i:i + 2] in ("//", "/*"):
            closer = "\n" if text[i:i + 2] == "//" else "*/"
            end = text.find(closer, i + 2)
            end = len(text) if end < 0 else end + len(closer)
            out.append("".join(c if c == "\n" else " " for c in text[i:end]))
            i = end
        elif text[i] in "\"'":
            quote = text[i]
            j = i + 1
            while j < len(text) and text[j] != quote and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            end = min(j + 1, len(text))
            out.append(quote)
            out.append("".join(c if c == "\n" else " " for c in text[i + 1:end]))
            i = end
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _call_arguments(original, blanked, start):
    """Source text of a call's arguments, from just after '(' to the match.

    `blanked` is the same line with comments and literal contents masked,
    so parentheses inside a string cannot close the call early. When the call
    does not close on this line, the rest of the line is returned: the rule is
    line-based and only claims what the line shows.
    """
    depth = 1
    index = start
    while index < len(blanked):
        if blanked[index] == "(":
            depth += 1
        elif blanked[index] == ")":
            depth -= 1
            if not depth:
                return original[start:index]
        index += 1
    return original[start:]


def _split_concat(text):
    """Split an expression on top-level '+', ignoring literals and brackets.

    `a + b(c + d)` has two operands, not three: the inner '+' belongs to the
    call. Quotes are tracked so a '+' inside a string does not split either.
    """
    parts = []
    start = 0
    depth = 0
    quote = None
    index = 0
    while index < len(text):
        char = text[index]
        if quote:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(0, depth - 1)
        elif char == "+" and depth == 0:
            parts.append(text[start:index])
            start = index + 1
        index += 1
    parts.append(text[start:])
    return [part.strip() for part in parts]


def _is_constant_operand(operand):
    """True when a '+' operand carries no value that can change at run time.

    `exec("logcat -d " + FILTER_SPEC)` is a fixed command plus a compile-time
    constant, not injection. `exec("convert " + path)` is: `path` is a value.
    Anything not recognised as a constant is treated as a value, so the rule
    errs toward silence only where the operand is provably fixed.
    """
    text = operand.strip().rstrip(";").strip()
    while text.endswith(")") and text.count("(") < text.count(")"):
        text = text[:-1].strip()
    if not text:
        return True
    if JVM_CONSTANT_OPERAND.match(text):
        return True
    if text.startswith("!") and JVM_CONSTANT_OPERAND.match(text[1:].strip()):
        return True
    return bool(JVM_UPPER_NAME.match(text.split(".")[-1].strip()))


def _jvm_defects(text):
    lines = text.split("\n")
    blanked_text = _blank_noncode(text)
    blank_lines = blanked_text.split("\n")
    found = []
    for number, raw in enumerate(lines, start=1):
        stripped = raw.strip()
        if stripped.startswith(("//", "*", "/*")):
            continue
        line_blanked = blank_lines[number - 1]

        exec_match = JVM_EXEC_CALL.search(line_blanked)
        if exec_match:
            operands = _split_concat(_call_arguments(raw, line_blanked, exec_match.end()))
            if len(operands) > 1 and any(not _is_constant_operand(o) for o in operands):
                found.append(("jvm-exec-injection", number, stripped[:300]))

        # `execute(` alone is not SQL: an executor, a command runner, or a
        # callback dispatcher all use the name. The line must also carry a
        # statement verb inside the call's arguments, so a concatenated log
        # tag or task key stays quiet.
        sql_match = JVM_SQL_CALL.search(line_blanked)
        if sql_match:
            arguments = _call_arguments(raw, line_blanked, sql_match.end())
            if JVM_SQL_VERB.search(arguments) and len(_split_concat(arguments)) > 1:
                found.append(("jvm-sql-injection", number, stripped[:300]))

        if JVM_WEAK_HASH.search(stripped):
            found.append(("jvm-weak-hash", number, stripped[:300]))
        if JVM_OBJECT_INPUT.search(line_blanked):
            found.append(("jvm-object-input-stream", number, stripped[:300]))
    return found


def detect_defects(files, tracked=None):
    """Return (findings, warnings). Findings are unranked: no reach/effort yet.

    `tracked` is the set of paths git reports as tracked, or None when the
    commit set is unknown. It restricts the config-secret rules only: a
    credential in an untracked `.env` is not committed, while a key hardcoded
    in source is a finding whether or not that source is committed.
    """
    findings = []
    warnings = []
    for f in files:
        rel = f["rel"]
        if f["ext"] in PY_EXT:
            result = _py_defects(f["text"])
            if result is None:
                warnings.append({"path": rel, "reason": "python parse error: AST rules skipped"})
                continue
            pairs = result
        elif f["ext"] in JS_EXT:
            pairs = _js_defects(f["text"])
        elif f["ext"] in JVM_EXT:
            # The Java/Kotlin secret patterns are the shared ones: no duplicate rule ids.
            pairs = _jvm_defects(f["text"]) + _line_hits(f["text"], SECRET_PATTERNS)
        elif is_config_secret_file(rel, f["ext"]):
            if tracked is not None and rel not in tracked:
                continue
            pairs = _config_defects(f["text"])
        else:
            continue

        seen = set()
        for rule, line, evidence in pairs:
            if (rule, line) in seen:
                continue
            seen.add((rule, line))
            taxonomy, blast, silence, message = META[rule]
            findings.append({
                "id": _id(rule, rel, line),
                "class": "defect",
                "rule": rule,
                "taxonomy": taxonomy,
                "file": rel,
                "line": line,
                "evidence": evidence,
                "message": message,
                "detector": "tool",
                "confidence": "high",
                "blast": blast,
                "silence": silence,
            })

    findings.sort(key=lambda x: (x["file"], x["line"], x["rule"]))
    return findings, warnings
