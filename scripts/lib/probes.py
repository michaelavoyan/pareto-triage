"""Probe templates and scaffold detection.

A scaffold is a template with placeholders filled and nothing else. It exists so
the first probe in a repo is a fill-in-the-blank, and it is refused by `verify`
while unfilled — an empty probe that exits non-zero would otherwise look like a
reproduction.
"""

import hashlib
import re
from pathlib import Path

SECTION_RE = re.compile(r"^## ([a-z-]+)\s*$(.*?)(?=^## |\Z)", re.M | re.S)
FENCE_RE = re.compile(r"```[a-z]*[ \t]*\n(.*?)```", re.S)
SCAFFOLD_RE = re.compile(r"^# scaffold: ([0-9a-f]+)$", re.M)
# Every template ends with this sentinel. While it is present, the file is still
# the template: a placeholder must never look like a failing test.
SENTINEL = "unfilled scaffold"

LANG_EXT = {"py": ".py", "ts": ".mjs", "js": ".mjs"}


def templates_path():
    return Path(__file__).resolve().parents[2] / "references" / "probes.md"


def templates(path=None):
    """taxonomy -> template body. Unknown taxonomies are absent, not invented."""
    document = Path(path) if path else templates_path()
    try:
        text = document.read_text(encoding="utf-8")
    except OSError:
        return {}

    found = {}
    for match in SECTION_RE.finditer(text):
        taxonomy = match.group(1).strip()
        fence = FENCE_RE.search(match.group(2))
        if fence:
            found[taxonomy] = fence.group(1)
    return found


def hash_of(body):
    normalised = "\n".join(line.rstrip() for line in body.strip().split("\n"))
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:16]


def render(taxonomy, cluster, site, path=None):
    """Return (body, extension) for a filled scaffold, or (None, None)."""
    body = templates(path).get(taxonomy)
    if body is None:
        return None, None
    digest = hash_of(body)
    filled = (body.replace("{{hash}}", digest)
                  .replace("{{cluster}}", str(cluster.get("key")))
                  .replace("{{file}}", str(cluster.get("file")))
                  .replace("{{line}}", str(cluster.get("line")))
                  .replace("{{function}}", str(cluster.get("function") or "handler")))
    return filled, LANG_EXT.get(((site or {}).get("lang") or "py"), ".py")


def scaffold_digest(text):
    match = SCAFFOLD_RE.search(text or "")
    return match.group(1) if match else None


def is_unfilled(text, path=None):
    """True while the file still carries the template's sentinel."""
    if SENTINEL not in (text or ""):
        return False
    return scaffold_digest(text) is not None
