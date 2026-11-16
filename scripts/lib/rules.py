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
    ("js-exec-interp", re.compile(r"\b(?:exec|execSync|spawnSync|spawn)\s*\(\s*`[^`]*\$\{")),
    ("js-tls-off", re.compile(r"rejectUnauthorized\s*:\s*false")),
    ("js-secret-aws", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("js-secret-pem", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("js-secret-stripe", re.compile(r"\bsk_live_[0-9A-Za-z]{16,}")),
    ("js-dangerous-html", re.compile(r"dangerouslySetInnerHTML\s*=\s*\{\{")),
]


def _js_defects(text):
    lines = text.split("\n")
    found = []
    for rule, pattern in JS_RULES:
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            stripped = lines[line - 1].strip()
            if stripped.startswith("//") or stripped.startswith("*"):
                continue
            found.append((rule, line, stripped[:300]))
    return found


def detect_defects(files):
    """Return (findings, warnings). Findings are unranked: no reach/effort yet."""
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
        elif f["ext"] in SECRET_EXTS or rel.rsplit("/", 1)[-1].startswith(".env"):
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
