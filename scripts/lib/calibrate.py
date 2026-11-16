"""Phase 2 calibration: sample findings, measure precision, gate on the number.

`prompts.md` asks for a sample of 20 findings checked against the source, and a
precision of 0.70 before the prompt is trusted. This module makes that a command
instead of an anecdote: the sample is deterministic, unfilled verdicts are
distinguishable from wrong ones, and the threshold is applied here rather than
in someone's memory.
"""

import hashlib
import json
import random

THRESHOLD = 0.70
MIN_SAMPLE = 20
VERDICTS = {"true": True, "false": False, "yes": True, "no": False, "1": True, "0": False}


def _seed(repo_name, seed):
    digest = hashlib.sha256(("%s:%s" % (repo_name, seed)).encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def sample(findings, size=MIN_SAMPLE, repo_name="", seed=0):
    """Stratified deterministic sample: round-robin across taxonomies, id order."""
    groups = {}
    for finding in sorted(findings, key=lambda f: f["id"]):
        groups.setdefault(finding.get("taxonomy") or finding["id"], []).append(finding)

    rng = random.Random(_seed(repo_name, seed))
    keys = sorted(groups)
    rng.shuffle(keys)
    for key in keys:
        rng.shuffle(groups[key])

    picked = []
    index = 0
    while len(picked) < size and any(groups[key] for key in keys):
        key = keys[index % len(keys)]
        if groups[key]:
            picked.append(groups[key].pop(0))
        index += 1
    return picked


def rows(findings):
    return [{"id": f["id"], "taxonomy": f.get("taxonomy"), "file": f.get("file"),
             "line": f.get("line"), "evidence": f.get("evidence"), "verdict": None}
            for f in findings]


def read_verdicts(text):
    """Return (records, unreadable_lines)."""
    records, bad = [], []
    for index, line in enumerate(text.split("\n"), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            bad.append(index)
            continue
        if not isinstance(record, dict):
            bad.append(index)
            continue
        record["verdict"] = VERDICTS.get(str(record.get("verdict", "")).strip().lower())
        records.append(record)
    return records, bad


def summarise(records):
    filled = [r for r in records if r["verdict"] is not None]
    correct = sum(1 for r in filled if r["verdict"] is True)

    by_taxonomy = {}
    for record in filled:
        bucket = by_taxonomy.setdefault(record.get("taxonomy") or "unknown",
                                        {"checked": 0, "correct": 0})
        bucket["checked"] += 1
        bucket["correct"] += 1 if record["verdict"] else 0

    precision = round(correct / len(filled), 3) if filled else None
    if len(filled) < MIN_SAMPLE:
        status = "incomplete"
    elif precision is not None and precision >= THRESHOLD:
        status = "pass"
    else:
        status = "fail"

    return {
        "sampled": len(records),
        "filled": len(filled),
        "correct": correct,
        "precision": precision,
        "threshold": THRESHOLD,
        "status": status,
        "by_taxonomy": {key: {"checked": value["checked"],
                              "precision": round(value["correct"] / value["checked"], 3)}
                        for key, value in sorted(by_taxonomy.items())},
        "note": ("below 0.70 means the prompt or the taxonomy is wrong; tune the prompt, "
                 "not the threshold" if status == "fail" else
                 "a sample under %d is insufficient to judge precision" % MIN_SAMPLE
                 if status == "incomplete" else
                 "precision meets the threshold for the sampled findings"),
    }
