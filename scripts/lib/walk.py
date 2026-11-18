"""File discovery and sizing for pareto-triage."""

import os
from pathlib import Path

IGNORE_DIRS = {
    "node_modules", "bower_components", "vendor", "dist", "build", "out", "coverage",
    ".next", ".nuxt", ".svelte-kit", ".turbo", ".cache", ".parcel-cache",
    "__pycache__", ".venv", "venv", "env", ".tox", ".mypy_cache", ".pytest_cache",
    "target", "bin", "obj", ".gradle", ".idea", ".vscode", ".terraform",
    "Pods", "Carthage", ".bundle", "tmp", "temp", "logs",
}

BINARY_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".ico", ".bmp", ".tiff",
    ".pdf", ".zip", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".tar",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".mp3", ".mp4", ".mov", ".avi", ".wav", ".flac", ".webm",
    ".so", ".dylib", ".dll", ".exe", ".class", ".o", ".a", ".pyc", ".wasm",
    ".sqlite", ".db", ".map",
}

MAX_BYTES = 2 * 1024 * 1024
MAX_FILES = 20000


TEST_DIR_SEGMENTS = ("/test/", "/tests/", "/androidtest/", "/androidtestdebug/",
                     "/__tests__/", "/spec/", "/testdata/", "/integrationtest/")

TEST_FILE_PATTERNS = [
    r"(^|/)[^/]+(Test|Tests|IT|Spec)\.(java|kt|kts|swift|m|mm)$",
    r"(^|/)test_[^/]+\.py$",
    r"(^|/)[^/]+_test\.py$",
    r"\.(test|spec)\.(ts|tsx|js|jsx|mjs)$",
]


def is_test_path(rel):
    """Test code is not on the request path, and judging it wastes phase 2."""
    import re

    lowered = "/" + rel.lower()
    if any(segment in lowered for segment in TEST_DIR_SEGMENTS):
        return True
    return any(re.search(pattern, rel, re.I) for pattern in TEST_FILE_PATTERNS)


def count_loc(text):
    """Non-blank lines. Blank lines are not code."""
    return sum(1 for line in text.split("\n") if line.strip())


def walk(root):
    root_path = Path(root).resolve()
    files = []
    skipped = []
    truncated = False

    for dirpath, dirnames, filenames in os.walk(root_path):
        if len(files) >= MAX_FILES:
            truncated = True
            break
        dirnames[:] = sorted(d for d in dirnames if d != ".git" and d not in IGNORE_DIRS)

        for name in sorted(filenames):
            abs_path = Path(dirpath) / name
            rel = abs_path.relative_to(root_path).as_posix()
            ext = abs_path.suffix.lower()

            if ext in BINARY_EXT:
                skipped.append({"path": rel, "reason": "binary extension"})
                continue
            try:
                size = abs_path.stat().st_size
            except OSError:
                continue
            if size > MAX_BYTES:
                skipped.append({"path": rel, "reason": "larger than %d bytes" % MAX_BYTES})
                continue
            try:
                raw = abs_path.read_bytes()
            except OSError:
                continue
            if b"\x00" in raw:
                skipped.append({"path": rel, "reason": "binary content"})
                continue
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                skipped.append({"path": rel, "reason": "not utf-8"})
                continue

            files.append({
                "abs": str(abs_path),
                "rel": rel,
                "ext": ext,
                "size": size,
                "text": text,
            })

    return {
        "root": str(root_path),
        "files": files,
        "skipped": skipped,
        "truncated": truncated,
    }
