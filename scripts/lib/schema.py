"""Data contract: the merge gate for findings."""

import json

TAXONOMIES = [
    "swallowed-exception",
    "missing-timeout",
    "no-retry",
    "no-backoff",
    "missing-idempotency",
    "unbounded-query",
    "unbounded-concurrency",
    "missing-boundary-validation",
    "missing-authz",
    "silent-default-fallback",
    "resource-leak",
    "non-atomic-write",
    "missing-cancellation",
]

DEFECT_TAXONOMIES = [
    "code-injection",
    "command-injection",
    "sql-injection",
    "unsafe-deserialization",
    "tls-verification-disabled",
    "hardcoded-secret",
    "mutable-default-arg",
    "bare-except",
    "weak-hash",
    "debug-mode-enabled",
    "xss",
]

RANGES = {"reach": (0, 5), "blast": (0, 5), "silence": (1, 3), "effort": (1, 5)}
CONFIDENCE = {"high", "med", "low"}
CONFIDENCE_ORDER = {"low": 0, "med": 1, "high": 2}


def apply_confidence_cap(finding, cap, reason=None):
    """Downgrade a finding to the gate's cap. Returns True when it changed."""
    if not cap:
        return False
    current = finding.get("confidence")
    if CONFIDENCE_ORDER.get(current, 0) <= CONFIDENCE_ORDER.get(cap, 0):
        return False
    finding["confidence"] = cap
    finding["confidence_capped"] = True
    if reason:
        finding["confidence_reason"] = reason
    return True


def _squash(value):
    return " ".join(str(value).split())


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def validate_finding(finding, sources=None, require_class=False):
    """Return a list of errors. Empty means valid."""
    if not isinstance(finding, dict):
        return ["not an object"]

    errors = []
    kind = finding.get("class")
    if require_class and kind != require_class:
        errors.append('class must be "%s", got %r' % (require_class, kind))
    if kind not in ("defect", "failure-mode"):
        errors.append('class must be "defect" or "failure-mode", got %r' % (kind,))
        return errors

    expected_taxonomies = TAXONOMIES if kind == "failure-mode" else DEFECT_TAXONOMIES
    doc = "taxonomy.md" if kind == "failure-mode" else "defect-rules.md"
    if finding.get("taxonomy") not in expected_taxonomies:
        errors.append("taxonomy must be one of %s, got %r" % (doc, finding.get("taxonomy")))

    required = ["file", "evidence"]
    if kind == "failure-mode":
        required.append("counter_evidence")
    for key in required:
        value = finding.get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append("%s is required and must be non-empty" % key)

    if not _is_int(finding.get("line")) or finding["line"] < 1:
        errors.append("line must be an integer >= 1")

    for key, (low, high) in RANGES.items():
        value = finding.get(key)
        if key == "effort" and kind == "failure-mode" and value is None:
            # Derived by rank from the rubric; the model does not supply it.
            continue
        if not _is_int(value) or value < low or value > high:
            errors.append("%s must be an integer in [%d, %d]" % (key, low, high))

    expected_detector = "llm" if kind == "failure-mode" else "tool"
    if finding.get("detector") != expected_detector:
        errors.append('detector must be "%s" for %s findings' % (expected_detector, kind))

    if finding.get("confidence") not in CONFIDENCE:
        errors.append("confidence must be high, med, or low")
    elif kind == "failure-mode" and finding.get("confidence") == "high":
        errors.append('confidence "high" is reserved for tool detectors')

    if sources is not None and isinstance(finding.get("file"), str) and isinstance(finding.get("evidence"), str):
        source = sources.get(finding["file"])
        if source is None:
            errors.append("file not in scanned set: %s" % finding["file"])
        elif _squash(finding["evidence"]) not in _squash(source):
            errors.append("evidence does not appear verbatim in the cited file (hallucination guard)")

    return errors


def parse_jsonl(text):
    records = []
    bad = []
    for index, line in enumerate(text.split("\n"), start=1):
        if not line.strip():
            continue
        try:
            records.append((index, json.loads(line)))
        except ValueError as exc:
            bad.append((index, "invalid JSON: %s" % exc))
    return records, bad
