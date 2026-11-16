"""Secret redaction for published artifacts.

`out/defects.jsonl` keeps raw evidence: the evidence guard has to prove the
string exists in the source, and a redacted quote cannot do that. Everything
published — `report.json` and `report.html` — goes through here first.

The redaction is deliberately lossy: it keeps the shape of the secret so a
reader can see what kind it is, and enough context to find the line, but not
the value.
"""

import re

AWS_ACCESS_KEY = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
STRIPE_LIVE = re.compile(r"\bsk_live_[0-9A-Za-z]{10,}\b")
PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    re.S)
KEY_NAMES = (r"password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|"
             r"client[_-]?secret")

# The key may be part of a longer identifier (DB_PASSWORD), but must not start
# mid-word. Values are only masked when they cannot be a code reference:
# a dotted expression or a template substitution is left alone.
QUOTED_ASSIGNMENT = re.compile(
    r"(?i)(?<![A-Za-z0-9])(" + KEY_NAMES + r")(\s*[:=]\s*)(['\"])([^'\"]{6,})\3")
UNQUOTED_ASSIGNMENT = re.compile(
    r"(?i)(?<![A-Za-z0-9])(" + KEY_NAMES + r")(\s*[:=]\s*)"
    r"(?=[A-Za-z0-9_\-+/=]*[0-9])[A-Za-z0-9_\-+/=]{6,}")

PLACEHOLDER = "\u2022" * 8


def _mask_quoted(match):
    return "%s%s%s%s%s" % (match.group(1), match.group(2), match.group(3),
                           PLACEHOLDER, match.group(3))


def _mask_unquoted(match):
    return "%s%s%s" % (match.group(1), match.group(2), PLACEHOLDER)


def redact(text):
    """Return (redacted_text, rules). `rules` is [] when nothing was secret."""
    if not text:
        return text, []

    rules = []
    masked = text

    def note(name, count):
        if count:
            rules.append({"rule": name, "count": count})

    masked, count = AWS_ACCESS_KEY.subn("AKIA" + PLACEHOLDER, masked)
    note("aws-access-key", count)

    masked, count = STRIPE_LIVE.subn("sk_live_" + PLACEHOLDER, masked)
    note("stripe-live-key", count)

    masked, count = PRIVATE_KEY.subn(
        "-----BEGIN PRIVATE KEY----- [redacted] -----END PRIVATE KEY-----", masked)
    note("private-key-block", count)

    masked, count = QUOTED_ASSIGNMENT.subn(_mask_quoted, masked)
    note("assigned-secret", count)

    masked, count = UNQUOTED_ASSIGNMENT.subn(_mask_unquoted, masked)
    note("assigned-secret", count)

    return masked, rules


def redact_findings(findings):
    """Redact in place. Returns one record per redaction, for the report."""
    redactions = []
    for finding in findings:
        evidence = finding.get("evidence")
        if not isinstance(evidence, str):
            continue
        masked, rules = redact(evidence)
        if not rules:
            continue
        finding["evidence"] = masked
        finding["redacted"] = True
        for rule in rules:
            redactions.append({
                "file": finding.get("file"),
                "line": finding.get("line"),
                "rule": rule["rule"],
                "count": rule["count"],
            })
    return redactions
