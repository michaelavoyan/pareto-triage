"""Language, framework, and test-runner detection."""

import json
import re
from pathlib import Path

from .walk import count_loc

EXT_LANG = {
    ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript", ".cts": "typescript",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".py": "python",
    ".go": "go", ".rs": "rust", ".java": "java", ".kt": "kotlin", ".kts": "kotlin",
    ".rb": "ruby",
    ".php": "php", ".cs": "csharp", ".swift": "swift", ".scala": "scala",
    ".m": "objc", ".mm": "objc",
    ".c": "c", ".cc": "cpp", ".cpp": "cpp", ".hpp": "cpp",
    ".vue": "vue", ".svelte": "svelte",
}

# `.h` is deliberately absent. Objective-C and C headers are import targets, not
# code that gets ranked: a header holds no function body and its lines are not
# implementation. Counting them would double every Objective-C size figure.
# The graph still indexes them, as sources of edges only.

SUPPORTED = {"typescript", "javascript", "python", "java", "kotlin", "swift", "objc"}

SUPPORTED_LABEL = ", ".join(sorted(SUPPORTED))

MANIFESTS = [
    "package.json", "tsconfig.json", "requirements.txt", "pyproject.toml",
    "setup.py", "setup.cfg", "go.mod", "Cargo.toml", "pom.xml", "build.gradle",
    "Gemfile", "composer.json",
]

FRAMEWORK_SIGNS = [
    ("express", "node", "package.json", r'"(express|koa|@nestjs/core|fastify|hapi)"\s*:'),
    ("next", "node", "package.json", r'"next"\s*:'),
    ("react", "node", "package.json", r'"react"\s*:'),
    ("fastapi", "python", "requirements.txt", r"(?i)fastapi"),
    ("fastapi", "python", "pyproject.toml", r'(?i)"?fastapi\b'),
    ("flask", "python", "requirements.txt", r"(?i)flask"),
    ("flask", "python", "pyproject.toml", r'(?i)"?flask\b'),
    ("django", "python", "requirements.txt", r"(?i)django"),
    ("django", "python", "pyproject.toml", r'(?i)"?django\b'),
    ("django", "python", "setup.py", r"(?i)django"),
]

TEST_SIGNS = [
    ("vitest", "package.json", r'"vitest"\s*:'),
    ("jest", "package.json", r'"jest"\s*:'),
    ("mocha", "package.json", r'"mocha"\s*:'),
    ("node:test", "package.json", r'"test"\s*:\s*"[^"]*node\s+--test'),
    ("pytest", "pyproject.toml", r"pytest"),
    ("pytest", "requirements.txt", r"(?i)pytest"),
    ("pytest", "setup.cfg", r"\[tool:pytest\]"),
]


def read_manifests(root):
    out = {}
    for name in MANIFESTS:
        path = Path(root) / name
        try:
            out[name] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
    return out


def languages(files):
    by = {}
    for f in files:
        lang = EXT_LANG.get(f["ext"])
        if not lang:
            continue
        slot = by.setdefault(lang, {"files": 0, "loc": 0})
        slot["files"] += 1
        slot["loc"] += count_loc(f["text"])
    return by


def frameworks(manifests):
    found = {}
    for name, ecosystem, filename, pattern in FRAMEWORK_SIGNS:
        text = manifests.get(filename)
        if text and re.search(pattern, text):
            found["%s@%s" % (name, ecosystem)] = {
                "name": name,
                "ecosystem": ecosystem,
                "evidence": filename,
            }
    return sorted(found.values(), key=lambda f: f["name"])


def test_runner(manifests, files):
    for runner, filename, pattern in TEST_SIGNS:
        text = manifests.get(filename)
        if text and re.search(pattern, text):
            return {"present": True, "runner": runner}
    for f in files:
        rel = f["rel"]
        if (re.search(r"(^|/)(tests?|__tests__|spec)/", rel, re.I)
                or re.search(r"\.(test|spec)\.[cm]?[jt]sx?$", rel)
                or re.search(r"(^|/)test_[^/]*\.py$", rel)):
            return {"present": True, "runner": "unknown", "evidence": rel}
    return {"present": False, "runner": None}


def split_supported(by_lang):
    supported = []
    unsupported = []
    for lang, stats in by_lang.items():
        entry = {"lang": lang, "files": stats["files"], "loc": stats["loc"]}
        (supported if lang in SUPPORTED else unsupported).append(entry)
    key = lambda e: -e["loc"]
    return sorted(supported, key=key), sorted(unsupported, key=key)
