"""Candidate sites for phase 2 enrichment.

Phase 2 asks a model to judge one function at a time. It needs a bounded,
deterministic list of functions that are actually reachable from an entrypoint,
not the whole repository. This module produces that list.

What it is not: a parser. Python uses `ast`; JavaScript, TypeScript, Java,
Kotlin, Swift and Objective-C use brace matching over regex-found headers. All
of it is approximate by design and documented in references/entrypoints.md. A
site whose bounds are wrong produces evidence that fails `pareto-triage
validate`, which is a visible failure rather than a silent one.

There are two ways to fill the cap. `random` shuffles the candidate population
with a seed and then applies the per-file cap; `ranked` keeps the old reach →
inbound → body size → path order. Random is the default because the ranked
order was measured against a seeded random sample on Signal-Android and came
out indistinguishable from it (see references/entrypoints.md). The ordering is
still available, but a reader must ask for it.
"""

import ast
import math
import random
import re

from .walk import is_test_path

JS_EXT = {".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs"}
PY_EXT = {".py"}
JVM_EXT = {".java", ".kt", ".kts"}
SWIFT_EXT = {".swift"}
OBJC_EXT = {".m", ".mm"}

LANG_BY_EXT = {
    ".ts": "ts", ".tsx": "ts", ".mts": "ts", ".cts": "ts",
    ".js": "js", ".jsx": "js", ".mjs": "js", ".cjs": "js",
    ".py": "py",
    ".java": "java", ".kt": "kotlin", ".kts": "kotlin",
    ".swift": "swift", ".m": "objc", ".mm": "objc",
}

MAX_SITES_DEFAULT = 400
MAX_SITES_PER_FILE = 20
SAMPLE_ORDERS = ("random", "ranked")
DEFAULT_SAMPLE_ORDER = "random"
DEFAULT_SEED = 0
COVERAGE_FLOOR = 1
ACCESSOR_RE = re.compile(r"^(get|set|is|has)[A-Z]")
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
    re.compile(r"^\s*#\s*(?:import|include)\s+.+$", re.M),
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

JVM_MODIFIERS = (
    r"(?:public|protected|private|static|final|abstract|synchronized|native|default|"
    r"strictfp|transient|volatile|sealed|non-sealed)"
)
KOTLIN_MODIFIERS = (
    r"(?:public|private|protected|internal|open|final|abstract|override|suspend|inline|"
    r"infix|operator|tailrec|external|expect|actual|data|enum|sealed|annotation|value|"
    r"inner|companion|fun)"
)
ANNOTATION_PREFIX = r"(?:@[A-Za-z_]\w*(?::[A-Za-z_]\w*)*(?:\([^)\n]*\))?[ \t]+)*"

# Java: `[modifiers] [<T>] [ReturnType] name(params)`. The return type is
# optional so constructors match; nothing here proves the name is a declaration,
# so `_jvm_sites` checks for a body and rejects call statements.
JAVA_METHOD_RE = re.compile(
    r"^[ \t]*" + ANNOTATION_PREFIX +
    r"(?:" + JVM_MODIFIERS + r"[ \t]+)*"
    r"(?:<[^>\n]+>[ \t]+)?"
    r"(?:[\w$.<>\[\],?]+[ \t]+)?"
    r"([A-Za-z_$][\w$]*)[ \t]*\(", re.M)

JAVA_CLASS_RE = re.compile(
    r"^[ \t]*" + ANNOTATION_PREFIX +
    r"(?:" + JVM_MODIFIERS + r"[ \t]+)*"
    r"(?:class|interface|enum|record)[ \t]+([A-Za-z_$][\w$]*)", re.M)

# Kotlin: `[modifiers] fun [<T>] [Receiver.]name(params)`. A receiver type is how
# `fun String.slug()` is written; dropping it keeps names bare, as in JS sites.
KOTLIN_FUN_RE = re.compile(
    r"^[ \t]*" + ANNOTATION_PREFIX +
    r"(?:" + KOTLIN_MODIFIERS + r"[ \t]+)*"
    r"fun[ \t]+(?:<[^>\n]+>[ \t]+)?"
    r"(?:[A-Za-z_][\w.<>?, ]*\.[ \t]*)?"
    r"([A-Za-z_]\w*)[ \t]*\(", re.M)

KOTLIN_CLASS_RE = re.compile(
    r"^[ \t]*" + ANNOTATION_PREFIX +
    r"(?:" + KOTLIN_MODIFIERS + r"[ \t]+)*"
    r"(?:class|interface|object)[ \t]+([A-Za-z_]\w*)", re.M)

JVM_KEYWORDS = {
    "if", "for", "while", "switch", "catch", "return", "new", "throw", "else",
    "do", "try", "synchronized", "assert", "case", "break", "continue", "this",
    "super", "package", "import", "class", "interface", "enum", "record",
}

# Swift declaration modifiers. `class` is here because `class func` and
# `class var` exist; type declarations are matched separately and backtrack out
# of it. `nonisolated`, `package`, and `distributed` are newer but appear in
# real code, and an unknown modifier would hide the declaration entirely.
SWIFT_MODIFIERS = (
    r"(?:public|private|fileprivate|internal|open|package|final|static|class|"
    r"override|required|convenience|mutating|nonmutating|nonisolated|isolated|"
    r"lazy|weak|unowned|dynamic|optional|indirect|distributed|prefix|postfix|infix)"
)

# A backticked name is legal Swift (`func `default`()`), so it is matched and
# unwrapped rather than dropped.
SWIFT_NAME = r"(`[^`\n]+`|[A-Za-z_]\w*)"

SWIFT_FUNC_RE = re.compile(
    r"^[ \t]*" + ANNOTATION_PREFIX +
    r"(?:" + SWIFT_MODIFIERS + r"[ \t]+)*"
    r"func[ \t]+" + SWIFT_NAME + r"[ \t]*(?:<[^>\n]*>)?[ \t]*\(",
    re.M)

SWIFT_INIT_RE = re.compile(
    r"^[ \t]*" + ANNOTATION_PREFIX +
    r"(?:" + SWIFT_MODIFIERS + r"[ \t]+)*"
    r"init[?!]?[ \t]*\(",
    re.M)

SWIFT_DEINIT_RE = re.compile(
    r"^[ \t]*" + ANNOTATION_PREFIX +
    r"(?:" + SWIFT_MODIFIERS + r"[ \t]+)*"
    r"deinit\b",
    re.M)

# A property site needs a body brace; the optional type annotation stops at
# `{`, `=`, or the newline so a stored property cannot swallow the next line.
# Only `var` is matched: `let` cannot have a computed body, and a local
# `let x: T?` would otherwise latch onto the `{` of the `if` beneath it.
SWIFT_PROPERTY_RE = re.compile(
    r"^[ \t]*" + ANNOTATION_PREFIX +
    r"(?:" + SWIFT_MODIFIERS + r"[ \t]+)*"
    r"var[ \t]+" + SWIFT_NAME + r"[ \t]*"
    r"(?::[^{=\n]+)?",
    re.M)

SWIFT_TYPE_RE = re.compile(
    r"^[ \t]*" + ANNOTATION_PREFIX +
    r"(?:" + SWIFT_MODIFIERS + r"[ \t]+)*"
    r"(?:class|struct|enum|protocol|extension|actor)[ \t]+([A-Za-z_]\w*)",
    re.M)

SWIFT_KEYWORDS = {
    "func", "var", "let", "init", "deinit", "subscript", "typealias", "case",
    "static", "class", "struct", "enum", "protocol", "extension", "actor",
}

# Start of a declaration on the next line: a bodyless `func` signature, a
# stored property, or `}` must not be stretched over the declaration below it.
SWIFT_DECLARATION_LINE_RE = re.compile(
    r"[ \t]*(?:@[A-Za-z_]|(?:public|private|fileprivate|internal|open|package|"
    r"final|static|class|override|required|convenience|lazy|weak|unowned|dynamic|"
    r"mutating|nonmutating|nonisolated|indirect|optional)[ \t]|"
    r"(?:func|var|let|init|deinit|case|subscript|typealias|associatedtype|"
    r"class|struct|enum|protocol|extension|actor|import)\b)")

SWIFT_CONTINUATION_RE = re.compile(r"(?:[=+\-*/%<>!&|^~?,.:]|&&|\|\|)[ \t]*$")

# Objective-C method declarations. The return type is scanned with paren
# matching because it can itself be a block type, `- (void (^)(BOOL))done`.
OBJC_METHOD_HEAD_RE = re.compile(r"^[ \t]*([+-])[ \t]*\(", re.M)
OBJC_IMPLEMENTATION_RE = re.compile(r"^[ \t]*@implementation[ \t]+([A-Za-z_]\w*)", re.M)
OBJC_END_RE = re.compile(r"^[ \t]*@end\b", re.M)

# `get`/`set` alone is a protocol property requirement, not an implementation.
SWIFT_ACCESSOR_ONLY_RE = re.compile(r"(?:get|set|_read|_modify|\s)*")


def _line_of(text, index):
    return text.count("\n", 0, index) + 1


def _skip_string(text, index):
    quote = text[index]
    # Java text blocks and Kotlin raw strings: an unterminated-at-first-quote
    # run would desynchronise every brace after it.
    if quote == '"' and text.startswith('"""', index):
        index += 3
        while index < len(text):
            if text.startswith('"""', index):
                return index + 3
            if text[index] == "\\":
                index += 2
                continue
            index += 1
        return index
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


def _paren_end(text, open_index):
    """Return the index of the paren closing text[open_index], or -1."""
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
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return -1


def _jvm_body(text, index, expression_body):
    """Find a method body from just after the closing paren.

    Returns ("brace", open_index), ("expression", index), or (None, -1). Java
    allows `throws …` before the brace; Kotlin allows a return type and `where`
    before either a brace or `= expression`. A blank line or `;`/`}` first means
    the declaration has no body (interface or abstract member).
    """
    limit = min(len(text), index + 400)
    while index < limit:
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
            return "brace", index
        if char == "=":
            if expression_body:
                return "expression", index
            return None, -1
        if char in ";}":
            return None, -1
        if char == "\n":
            cursor = index + 1
            while cursor < len(text) and text[cursor] in " \t\r":
                cursor += 1
            if cursor < len(text) and text[cursor] == "\n":
                return None, -1
        index += 1
    return None, -1


def _expression_end(text, index):
    """End of an `= expression` body: its line, extended by open brackets."""
    depth = 0
    while index < len(text):
        char = text[index]
        if char in "\"'`":
            index = _skip_string(text, index)
            continue
        if char == "/" and text.startswith("//", index):
            newline = text.find("\n", index)
            if newline < 0:
                return len(text) - 1
            index = newline
            continue
        if char == "/" and text.startswith("/*", index):
            close = text.find("*/", index + 2)
            if close < 0:
                return len(text) - 1
            index = close + 2
            continue
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "\n" and depth <= 0:
            return max(0, index - 1)
        index += 1
    return len(text) - 1


def _class_body(text, index):
    """The brace that opens a class body, or -1 when the type has none.

    Only the header line and an Allman-style brace on the next line count. A
    body-less `data class Point(val x: Int)` must not swallow the next class.
    """
    line_end = text.find("\n", index)
    if line_end < 0:
        line_end = len(text)
    cursor = index
    while cursor < line_end:
        char = text[cursor]
        if char in "\"'`":
            cursor = _skip_string(text, cursor)
            continue
        if char == "{":
            return cursor
        if char == "/" and text.startswith("//", cursor):
            return -1
        cursor += 1
    cursor = line_end
    while cursor < len(text) and text[cursor] in "\n\r \t":
        cursor += 1
    if cursor < len(text) and text[cursor] == "{":
        return cursor
    return -1


def _type_declaration_before(text, index):
    """True when `index` names a type, not a call: `new Foo(`, `class Foo(`."""
    line_start = text.rfind("\n", 0, index) + 1
    return bool(re.search(r"\b(?:class|interface|enum|record|new)\s+$",
                          text[line_start:index]))


def _annotation_line(lines, line):
    """Start of a declaration plus annotations on the lines directly above."""
    index = line - 1
    while index > 0:
        previous = lines[index - 1].strip()
        if not previous.startswith("@") or previous.endswith("("):
            break
        index -= 1
    return index + 1


def _jvm_sites(text, rel):
    lines = text.split("\n")
    out = []
    if rel.endswith(".java"):
        patterns = ((JAVA_METHOD_RE, "method"), (JAVA_CLASS_RE, "class"))
    else:
        patterns = ((KOTLIN_FUN_RE, "method"), (KOTLIN_CLASS_RE, "class"))
    for pattern, kind in patterns:
        for match in pattern.finditer(text):
            name = match.group(1)
            if name in JVM_KEYWORDS:
                continue
            if kind == "method" and _type_declaration_before(text, match.start(1)):
                continue
            start = _annotation_line(lines, _line_of(text, match.start()))
            if kind == "class":
                body = _class_body(text, match.end())
                if body < 0:
                    continue
                close = _match_brace(text, body)
                end_index = close if close >= 0 else len(text) - 1
            else:
                close_paren = _paren_end(text, match.end() - 1)
                if close_paren < 0:
                    continue
                style, body = _jvm_body(text, close_paren + 1, pattern is KOTLIN_FUN_RE)
                if style is None:
                    continue
                if style == "brace":
                    close = _match_brace(text, body)
                    end_index = close if close >= 0 else len(text) - 1
                else:
                    end_index = _expression_end(text, body)
            out.append({
                "name": name,
                "kind": kind,
                "start": start,
                "end": max(start, _line_of(text, end_index)),
            })
    return out


def _skip_block_comment(text, index):
    """Index just past a block comment, allowing Swift's nested comments."""
    depth = 0
    while index < len(text):
        if text.startswith("/*", index):
            depth += 1
            index += 2
            continue
        if text.startswith("*/", index):
            depth -= 1
            index += 2
            if depth <= 0:
                return index
            continue
        index += 1
    return index


def _swift_string_start(text, index):
    """True when a Swift string literal opens at `index` (raw hashes included)."""
    cursor = index
    while cursor < len(text) and text[cursor] == "#":
        cursor += 1
    return cursor < len(text) and text[cursor] == '"'


def _swift_interpolation_end(text, index):
    """Index just past the `)` closing an interpolation opened at `index`."""
    parens = 0
    braces = 0
    while index < len(text):
        char = text[index]
        if char == '"' or (char == "#" and _swift_string_start(text, index)):
            index = _swift_skip_string(text, index)
            continue
        if char == "/" and text.startswith("//", index):
            newline = text.find("\n", index)
            index = len(text) if newline < 0 else newline
            continue
        if char == "/" and text.startswith("/*", index):
            index = _skip_block_comment(text, index)
            continue
        if char == "(":
            parens += 1
        elif char == ")":
            parens -= 1
            if parens == 0 and braces == 0:
                return index + 1
        elif char == "{":
            braces += 1
        elif char == "}":
            braces -= 1
        index += 1
    return index


def _swift_skip_string(text, index):
    """Index just past a Swift string literal at `index`.

    Handles `\"\"\"` multi-line strings, `#\"…\"#` / `##\"…\"##` raw strings whose
    terminator repeats the hash count, and `\\(…)` interpolation. Interpolation is
    scanned as code because it can hold another string, and therefore another
    quote, which a plain skip would mistake for the end of the literal.
    """
    hashes = 0
    cursor = index
    while cursor < len(text) and text[cursor] == "#":
        hashes += 1
        cursor += 1
    if cursor >= len(text) or text[cursor] != '"':
        return index + 1
    quotes = 3 if text.startswith('"""', cursor) else 1
    cursor += quotes
    terminator = '"' * quotes + "#" * hashes
    escape = "\\" + "#" * hashes
    while cursor < len(text):
        if text.startswith(terminator, cursor):
            return cursor + len(terminator)
        if text.startswith(escape, cursor):
            after = cursor + len(escape)
            if after < len(text) and text[after] == "(":
                cursor = _swift_interpolation_end(text, after)
                continue
            cursor = after + 1
            continue
        cursor += 1
    return cursor


def _swift_match_brace(text, open_index):
    """Return the index of the brace closing text[open_index], or -1."""
    depth = 0
    index = open_index
    while index < len(text):
        char = text[index]
        if char == '"' or (char == "#" and _swift_string_start(text, index)):
            index = _swift_skip_string(text, index)
            continue
        if char == "/" and text.startswith("//", index):
            newline = text.find("\n", index)
            index = len(text) if newline < 0 else newline
            continue
        if char == "/" and text.startswith("/*", index):
            index = _skip_block_comment(text, index)
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return -1


def _swift_paren_end(text, open_index):
    """Return the index of the paren closing text[open_index], or -1."""
    depth = 0
    index = open_index
    while index < len(text):
        char = text[index]
        if char == '"' or (char == "#" and _swift_string_start(text, index)):
            index = _swift_skip_string(text, index)
            continue
        if char == "/" and text.startswith("//", index):
            newline = text.find("\n", index)
            index = len(text) if newline < 0 else newline
            continue
        if char == "/" and text.startswith("/*", index):
            index = _skip_block_comment(text, index)
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return -1


def _swift_body(text, index, expression_body, same_line=False):
    """Find a Swift declaration body from just after its signature.

    Returns ("brace", open_index), ("expression", index), or (None, -1). A
    blank line, `}`/`;`, or a line that starts another declaration means this
    one has no body, so a protocol requirement or stored property cannot stretch
    over the function or property below it.

    `same_line` restricts a brace to the declaration's own line or the first
    character of the next one. A computed property is written that way; a local
    `var` followed by an `if` is not a property, and without the restriction its
    body would run to the `if`'s closing brace.
    """
    limit = min(len(text), index + 400)
    while index < limit:
        char = text[index]
        if char == '"' or (char == "#" and _swift_string_start(text, index)):
            index = _swift_skip_string(text, index)
            continue
        if char == "/" and text.startswith("//", index):
            newline = text.find("\n", index)
            index = len(text) if newline < 0 else newline
            continue
        if char == "/" and text.startswith("/*", index):
            index = _skip_block_comment(text, index)
            continue
        if char == "{":
            return "brace", index
        if char == "=":
            if expression_body:
                return "expression", index
            return None, -1
        if char in ";}":
            return None, -1
        if char == "\n":
            cursor = index + 1
            while cursor < len(text) and text[cursor] in " \t\r":
                cursor += 1
            if same_line:
                if cursor < len(text) and text[cursor] == "{":
                    return "brace", cursor
                return None, -1
            if cursor < len(text) and text[cursor] == "\n":
                return None, -1
            if cursor < len(text) and SWIFT_DECLARATION_LINE_RE.match(text, cursor):
                return None, -1
        index += 1
    return None, -1


def _swift_expression_end(text, index):
    """End of an `= expression` body: its line, extended by open brackets.

    A trailing operator, comma, dot, or colon continues the expression onto the
    next line. An operator at the end of a line is how Swift wraps a single
    expression without brackets; the next line is checked for a declaration so
    the wrap cannot swallow the declaration that follows.
    """
    depth = 0
    while index < len(text):
        char = text[index]
        if char == '"' or (char == "#" and _swift_string_start(text, index)):
            index = _swift_skip_string(text, index)
            continue
        if char == "/" and text.startswith("//", index):
            newline = text.find("\n", index)
            if newline < 0:
                return len(text) - 1
            index = newline
            continue
        if char == "/" and text.startswith("/*", index):
            index = _skip_block_comment(text, index)
            continue
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "\n" and depth <= 0:
            line_start = text.rfind("\n", 0, index) + 1
            next_start = index + 1
            while next_start < len(text) and text[next_start] in " \t\r":
                next_start += 1
            if (not SWIFT_CONTINUATION_RE.search(text[line_start:index])
                    or SWIFT_DECLARATION_LINE_RE.match(text, next_start)):
                return max(0, index - 1)
        index += 1
    return len(text) - 1


def _swift_sites(text, rel):
    lines = text.split("\n")
    out = []

    for match in SWIFT_FUNC_RE.finditer(text):
        name = match.group(1).strip("`")
        if name in SWIFT_KEYWORDS:
            continue
        close_paren = _swift_paren_end(text, match.end() - 1)
        if close_paren < 0:
            continue
        style, body = _swift_body(text, close_paren + 1, True)
        if style is None:
            continue
        if style == "brace":
            close = _swift_match_brace(text, body)
            end_index = close if close >= 0 else len(text) - 1
        else:
            end_index = _swift_expression_end(text, body)
            # `func f() -> Int = expr` is a site only when the expression wraps:
            # a one-line body names no failure mode a line of source can carry.
            if _line_of(text, body) == _line_of(text, end_index):
                continue
        start = _annotation_line(lines, _line_of(text, match.start()))
        out.append({
            "name": name,
            "start": start,
            "end": max(start, _line_of(text, end_index)),
        })

    for match in SWIFT_INIT_RE.finditer(text):
        close_paren = _swift_paren_end(text, match.end() - 1)
        if close_paren < 0:
            continue
        style, body = _swift_body(text, close_paren + 1, False)
        if style != "brace":
            continue
        close = _swift_match_brace(text, body)
        end_index = close if close >= 0 else len(text) - 1
        start = _annotation_line(lines, _line_of(text, match.start()))
        out.append({
            "name": "init",
            "start": start,
            "end": max(start, _line_of(text, end_index)),
        })

    for match in SWIFT_DEINIT_RE.finditer(text):
        style, body = _swift_body(text, match.end(), False)
        if style != "brace":
            continue
        close = _swift_match_brace(text, body)
        end_index = close if close >= 0 else len(text) - 1
        start = _annotation_line(lines, _line_of(text, match.start()))
        out.append({
            "name": "deinit",
            "start": start,
            "end": max(start, _line_of(text, end_index)),
        })

    for match in SWIFT_PROPERTY_RE.finditer(text):
        name = match.group(1).strip("`")
        style, body = _swift_body(text, match.end(), False, same_line=True)
        if style != "brace":
            continue  # stored property: no body, not a site
        close = _swift_match_brace(text, body)
        if close < 0:
            continue
        if SWIFT_ACCESSOR_ONLY_RE.fullmatch(text[body + 1:close]):
            continue  # a protocol's `{ get set }` requirement has no body
        start = _annotation_line(lines, _line_of(text, match.start()))
        out.append({
            "name": name,
            "start": start,
            "end": max(start, _line_of(text, close)),
        })

    for match in SWIFT_TYPE_RE.finditer(text):
        name = match.group(1)
        if name in SWIFT_KEYWORDS:
            continue
        style, body = _swift_body(text, match.end(), False)
        if style != "brace":
            continue
        close = _swift_match_brace(text, body)
        end_index = close if close >= 0 else len(text) - 1
        start = _annotation_line(lines, _line_of(text, match.start()))
        out.append({
            "name": name,
            "start": start,
            "end": max(start, _line_of(text, end_index)),
        })

    return out


def _objc_body(text, index):
    """The brace that opens an Objective-C method body, or -1.

    The signature may wrap over several lines, so the scan does not stop at a
    newline; `;` ends a declaration with no body (a protocol or interface
    member).
    """
    limit = min(len(text), index + 2000)
    while index < limit:
        char = text[index]
        if char in "\"'":
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
            return index
        if char == ";":
            return -1
        index += 1
    return -1


def _objc_container_spans(text):
    """`@implementation Name` … `@end` ranges, used only for `enclosed_by`."""
    spans = []
    for match in OBJC_IMPLEMENTATION_RE.finditer(text):
        end = OBJC_END_RE.search(text, match.end())
        spans.append((match.start(), end.start() if end else len(text), match.group(1)))
    return spans


def _objc_sites(text, rel):
    out = []
    spans = _objc_container_spans(text)
    for match in OBJC_METHOD_HEAD_RE.finditer(text):
        close_type = _paren_end(text, match.end() - 1)
        if close_type < 0:
            continue
        cursor = close_type + 1
        while cursor < len(text) and text[cursor] in " \t":
            cursor += 1
        name_match = re.match(r"[A-Za-z_]\w*", text[cursor:])
        if not name_match:
            continue
        name = name_match.group(0)
        body = _objc_body(text, cursor + name_match.end())
        if body < 0:
            continue
        close = _match_brace(text, body)
        end_index = close if close >= 0 else len(text) - 1
        site = {
            "name": name,
            "start": _line_of(text, match.start()),
            "end": _line_of(text, end_index),
        }
        container = [name for start, end, name in spans
                     if start < match.start() < end]
        if container:
            site["enclosed_by"] = [container[-1]]
        out.append(site)
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


CONSTRUCTOR_LINE_LIMIT = 5


def _is_constructor(site):
    """True for a constructor declaration, not a class body or a same-named fun.

    The declaration line is the discriminator: a constructor is `[modifiers]
    ClassName(`, while a Kotlin `fun clock(` starts with `fun` and a class body
    starts with `class`. The site extractor never emits a Kotlin constructor.
    """
    name = site["function"]
    if name != site["file"].rsplit("/", 1)[-1].split(".")[0]:
        return False
    return re.search(
        r"^[ \t]*" + ANNOTATION_PREFIX
        + r"(?:(?:public|protected|private|strictfp)[ \t]+)*"
        + re.escape(name) + r"[ \t]*\(",
        site["source"], re.M) is not None


def _constructor_lines(site):
    """Lines a constructor occupies, counting its signature and body.

    A six-line constructor is likely to validate or derive state; a three- or
    four-line one is field assignment. The wider of the recorded span and the
    physical body is used so a caller that supplies one but not the other still
    gets the same decision.
    """
    span = len(site["source"].split("\n"))
    if isinstance(site.get("lines"), (list, tuple)) and len(site["lines"]) == 2:
        span = max(span, site["lines"][1] - site["lines"][0] + 1)
    return span


def is_trivial_accessor(site):
    """A setter, getter, or assignment-only body is not worth judging."""
    body = [line.strip() for line in site["source"].split("\n") if line.strip()]
    if _is_constructor(site):
        # A constructor named after its class used to be exempt, which put
        # four-line field assignments such as MismatchedDevicesException.<init>
        # on the board. Only a constructor long enough to hold real logic stays.
        return _constructor_lines(site) <= CONSTRUCTOR_LINE_LIMIT
    if len(body) > 3:
        return False
    if ACCESSOR_RE.match(site["function"]):
        return True
    inner = body[1:-1]
    return bool(inner) and all(
        re.match(r"^(this\.)?[\w.]+\s*=\s*[^;]+;?$", line) for line in inner)


def _body_lines(site):
    return site["lines"][1] - site["lines"][0] + 1


JUDGEABLE_MIN_LINES = 4

# A site with a failure surface has something a phase-2 judgment can be about:
# an error path, an async boundary, a network call, a write, or a loop. Labels
# are reported, so a measurement can say which surface was found.
FAILURE_SURFACE_PATTERNS = (
    ("try/catch", re.compile(r"\b(?:try|catch)\b")),
    ("async", re.compile(r"\b(?:await|suspend|withContext)\b")),
    ("network", re.compile(
        r"\b(?:fetch|axios|urlopen|HttpClient|HttpURLConnection|HttpRequest|"
        r"OkHttpClient|WebClient|Retrofit|URLConnection|openConnection|newCall|"
        r"requests\.(?:get|post|put|patch|delete)|Socket|socket)\b"
        r"|https?://|wss?://")),
    ("db write", re.compile(r"\b(?:insert|update|delete|execute)\b|\brun\s*\(", re.I)),
    ("loop", re.compile(r"\b(?:for|while)\b|\bdo\s*\{|\.forEach\b|\brepeat\s*\(")),
)


def body_size(site):
    """Non-blank lines in the body the site records."""
    return sum(1 for line in (site.get("source") or "").split("\n") if line.strip())


def failure_surface(site):
    """Labels of the failure-surface constructs in a site's body.

    Mechanical only: it says `try` or `newCall` appears, not that the code
    handles failures well. That judgment is what phase 2 exists to make.
    """
    body = site.get("source") or ""
    return [label for label, pattern in FAILURE_SURFACE_PATTERNS if pattern.search(body)]


def is_judgeable(site):
    """Worth a phase-2 judgment: enough body to read, and something to fail.

    Sites of three lines or fewer are declarations, one-liners, or plumbing;
    phase 2 can only restate them. Without a failure surface there is nothing
    to judge even in a long body.
    """
    return body_size(site) >= JUDGEABLE_MIN_LINES and bool(failure_surface(site))


def _ordered_sites(candidates, inbound):
    """The ranked selection order: reach, inbound edges, body size, then path.

    Deterministic. Path order is the last tiebreak, never the first, because
    reach ties are the norm and path order favours one directory. This order is
    what `--sample-order ranked` asks for; it is not the default.
    """
    return sorted(candidates, key=lambda site: (
        -site["reach"],
        -inbound.get(site["file"], 0),
        -min(_body_lines(site), 200),
        site["file"],
        site["lines"][0],
        site["function"],
    ))


def _permutation(size, seed):
    """A seeded Fisher-Yates permutation of range(size).

    `randrange` only, over a Mersenne Twister stream, so the permutation is
    stable across Python versions and processes. Same size and seed give the
    same permutation, which is what makes `--seed` a reproducible choice.
    """
    rng = random.Random(seed)
    pool = list(range(size))
    for position in range(size - 1, 0, -1):
        swap = rng.randrange(position + 1)
        pool[position], pool[swap] = pool[swap], pool[position]
    return pool


def coverage_size(judgeable, fraction):
    """Sites a coverage fraction asks for: `max(floor, ceil(fraction * n))`.

    The floor is one: a non-zero fraction never draws an empty sample, and a
    repo with no judgeable site draws nothing at all.
    """
    if judgeable <= 0:
        return 0
    return max(COVERAGE_FLOOR, math.ceil(fraction * judgeable))


def _allocate_strata(counts, n):
    """Proportional allocation over reach bands, with one seat per band.

    `counts` maps a reach band to its judgeable population. Every band present
    gets a seat when `n` allows it, so the sample cannot lose the rarest reach
    level to rounding. The remainder goes by largest fraction, ties to the
    higher band. When `n` is smaller than the number of bands, the bands with
    the largest populations take the seats; representing all of them is then
    impossible and the allocation does not pretend otherwise.
    """
    bands = sorted(counts)
    total = sum(counts.values())
    if n >= total:
        return dict(counts)
    if n <= 0:
        return {band: 0 for band in bands}
    if n <= len(bands):
        winners = set(sorted(bands, key=lambda band: (-counts[band], -band))[:n])
        return {band: (1 if band in winners else 0) for band in bands}

    quotas = {band: n * counts[band] / total for band in bands}
    allocation = {band: int(quotas[band]) for band in bands}
    for band in bands:
        if allocation[band]:
            continue
        donor = max((other for other in bands if allocation[other] > 1),
                    key=lambda other: (allocation[other], other))
        allocation[donor] -= 1
        allocation[band] = 1

    remaining = n - sum(allocation.values())
    order = sorted(bands, key=lambda band: (-(quotas[band] - int(quotas[band])), -band))
    while remaining > 0:
        advanced = False
        for band in order:
            if remaining <= 0:
                break
            if allocation[band] < counts[band]:
                allocation[band] += 1
                remaining -= 1
                advanced = True
        if not advanced:
            break
    return allocation


def _fill_selection(indexes, ranked, limit, per_file, selected=None, counts=None):
    """Walk `indexes` in order, adding sites while the per-file cap and limit hold.

    Returns the selected ranked-index list and the per-file counts, so a
    fallback pass can continue where this one stopped.
    """
    selected = list(selected or [])
    counts = dict(counts or {})
    for index in indexes:
        site = ranked[index]
        if counts.get(site["file"], 0) >= per_file:
            continue
        counts[site["file"]] = counts.get(site["file"], 0) + 1
        selected.append(index)
        if len(selected) >= limit:
            break
    return selected, counts


def select_sites(candidates, inbound, limit=MAX_SITES_DEFAULT,
                 per_file=MAX_SITES_PER_FILE, order=DEFAULT_SAMPLE_ORDER,
                 seed=DEFAULT_SEED, judgeable=False, coverage=None):
    """Pick the sites worth judging. See `select_sites_with_remainder`."""
    selected, _, _ = select_sites_with_remainder(
        candidates, inbound, limit=limit, per_file=per_file, order=order,
        seed=seed, judgeable=judgeable, coverage=coverage)
    return selected


def select_sites_with_remainder(candidates, inbound, limit=MAX_SITES_DEFAULT,
                                per_file=MAX_SITES_PER_FILE,
                                order=DEFAULT_SAMPLE_ORDER, seed=DEFAULT_SEED,
                                judgeable=False, coverage=None):
    """Return (selected, population, plan) where the population starts with `selected`.

    `random` shuffles the ranked candidate list with `seed`; `ranked` walks the
    old order. Either way the per-file cap holds and the sample is drawn per
    reach band, proportionally: a repo with reach 2 and 5 sites keeps both
    bands, and a large reach-2 population does not crowd reach 5 out.

    With `judgeable`, only sites `is_judgeable` accepts fill the cap. The filter
    is applied here, in the sampling step, and never to the population: the
    remainder still lists every candidate, filtered or not, because
    `candidates.jsonl` is the population, not the sample. When fewer judgeable
    sites exist than the cap, the rest is filled from the non-judgeable
    remainder in ranked order and `plan["fallback"]` says how many.

    With `coverage`, the cap is `max(1, ceil(coverage * judgeable))` instead of
    `limit`; the two are mutually exclusive at the CLI.
    """
    ranked = _ordered_sites(candidates, inbound)
    if order == "random":
        permutation = _permutation(len(ranked), seed)
    elif order == "ranked":
        permutation = None
    else:
        raise ValueError("unknown sample order: %r" % (order,))

    if judgeable:
        eligible = [index for index, site in enumerate(ranked) if is_judgeable(site)]
    else:
        eligible = list(range(len(ranked)))

    if permutation is None:
        ordered_indexes = eligible
    else:
        allowed = set(eligible)
        ordered_indexes = [index for index in permutation if index in allowed]

    target = coverage_size(len(eligible), coverage) if coverage is not None else limit
    band_counts = {}
    for index in eligible:
        band = ranked[index]["reach"]
        band_counts[band] = band_counts.get(band, 0) + 1
    allocation = _allocate_strata(band_counts, target)

    selected_indexes, counts = [], {}
    for band in sorted(allocation, reverse=True):
        seats = allocation[band]
        if seats <= 0:
            continue
        stratum = [index for index in ordered_indexes if ranked[index]["reach"] == band]
        selected_indexes, counts = _fill_selection(
            stratum, ranked, len(selected_indexes) + seats, per_file,
            selected=selected_indexes, counts=counts)

    if len(selected_indexes) < target:
        taken = set(selected_indexes)
        rest = [index for index in ordered_indexes if index not in taken]
        selected_indexes, counts = _fill_selection(
            rest, ranked, target, per_file, selected=selected_indexes, counts=counts)

    fallback = 0
    if judgeable and len(selected_indexes) < target:
        eligible_set = set(eligible)
        remainder = (index for index in range(len(ranked)) if index not in eligible_set)
        before = len(selected_indexes)
        selected_indexes, counts = _fill_selection(
            remainder, ranked, target, per_file, selected=selected_indexes, counts=counts)
        fallback = len(selected_indexes) - before

    selected = [ranked[index] for index in selected_indexes]
    taken = set(selected_indexes)
    rest = [site for index, site in enumerate(ranked) if index not in taken]
    strata = {}
    for index in selected_indexes:
        band = ranked[index]["reach"]
        strata[str(band)] = strata.get(str(band), 0) + 1
    plan = {
        "judgeable": len(eligible),
        "filtered": len(ranked) - len(eligible),
        "fallback": fallback,
        "target": target,
        "strata": dict(sorted(strata.items(), key=lambda item: int(item[0]), reverse=True)),
    }
    return selected, selected + rest, plan


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
                  min_reach=2, include_enclosing=False, all_sites=False,
                  order=DEFAULT_SAMPLE_ORDER, seed=DEFAULT_SEED, coverage=None):
    """Return (sites, summary). Sites are ordered deterministically.

    With `all_sites`, the returned list is the whole population with the
    selected sites first; otherwise it is only the selected sites. With
    `coverage`, the cap is derived from the judgeable population instead of
    `max_sites`.
    """
    candidates = []
    parse_errors = []
    unreachable_files = 0
    test_files = 0

    for f in files:
        rel = f["rel"]
        ext = f["ext"]
        if ext not in JS_EXT and ext not in PY_EXT and ext not in JVM_EXT \
                and ext not in SWIFT_EXT and ext not in OBJC_EXT:
            continue
        if is_test_path(rel):
            test_files += 1
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
        elif ext in JVM_EXT:
            found = _jvm_sites(text, rel)
        elif ext in SWIFT_EXT:
            found = _swift_sites(text, rel)
        elif ext in OBJC_EXT:
            found = _objc_sites(text, rel)
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
                **({"enclosed_by": item["enclosed_by"]} if item.get("enclosed_by") else {}),
            })

    collapsed = extract_sites_collapse(candidates, include_enclosing)
    trivial = [site for site in collapsed if is_trivial_accessor(site)]
    judged = [site for site in collapsed if not is_trivial_accessor(site)]

    from .imports import inbound_counts
    inbound = inbound_counts(files)
    total = len(judged)
    judgeable_total = sum(1 for site in judged if is_judgeable(site))
    cap = (coverage_size(judgeable_total, coverage)
           if coverage is not None else max_sites)
    # A coverage fraction is a share of the judgeable sites, so the per-file
    # cap — a guard against one huge class owning a fixed-size sample — is
    # lifted: capping would make "coverage 1.0" quietly drop sites.
    per_file = (cap if coverage is not None
                else max(3, min(MAX_SITES_PER_FILE, max(cap, 1) // 5)))
    selected, population, plan = select_sites_with_remainder(
        judged, inbound, limit=cap, per_file=per_file, order=order,
        seed=seed, judgeable=True, coverage=coverage)
    chosen = population if all_sites else selected

    sites = []
    for index, site in enumerate(chosen, start=1):
        record = {"site_id": "s_%03d" % index}
        record.update(site)
        sites.append(record)

    summary = {
        "candidates": total,
        "emitted": len(selected),
        "population": len(population),
        "all_sites": all_sites,
        "limit": cap,
        "cap": cap,
        "coverage": coverage,
        "strata": plan["strata"],
        "per_file": per_file,
        "limit_hit": total > cap,
        "order": order,
        "seed": seed,
        "parse_errors": parse_errors,
        "unreachable_source_files": unreachable_files,
        "trivial_excluded": len(trivial),
        "test_files_excluded": test_files,
        "judgeable_candidates": plan["judgeable"],
        "judgeable_filtered": plan["filtered"],
        "judgeable_fallback": plan["fallback"],
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
