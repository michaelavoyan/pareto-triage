"""The enrichment prompt's identity.

`prompts.md` says its hash must be pinned in the report: findings produced under
one prompt are not comparable with findings produced under another. This module
is the single place that derives the prompt hash, so `rank`, `report`,
and `validate` cannot disagree.
"""

import hashlib
import re
from pathlib import Path

PROMPT_SECTION_RE = re.compile(r"^## Prompt[ \t]*$(.*?)^## ", re.M | re.S)
FENCE_RE = re.compile(r"```[a-z]*[ \t]*\n(.*?)```", re.S)
CATEGORY_LINE_RE = re.compile(r"^[ \t]*(swallowed-exception,.*)$", re.M)


def _normalise(text):
    """Whitespace and trailing blanks are not a prompt change."""
    lines = [line.rstrip() for line in text.strip().split("\n")]
    return "\n".join(line for line in lines if line)


def prompt_path(repo_root=None):
    if repo_root is not None:
        return Path(repo_root) / "references" / "prompts.md"
    return Path(__file__).resolve().parents[2] / "references" / "prompts.md"


def identity(path=None):
    """Return {"hash"} for the prompt. Never raises on a missing file.

    The hash is the identity: it cannot drift from the text. A hand-maintained
    version string could, and did.
    """
    document = Path(path) if path else prompt_path()
    try:
        text = document.read_text(encoding="utf-8")
    except OSError:
        return {"hash": None}

    section = PROMPT_SECTION_RE.search(text)
    body = ""
    if section:
        fence = FENCE_RE.search(section.group(1))
        if fence:
            body = fence.group(1)

    categories = CATEGORY_LINE_RE.search(text)
    payload = _normalise(body)
    if categories:
        payload += "\n" + _normalise(categories.group(1))

    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16] if payload else None
    return {"hash": digest}
