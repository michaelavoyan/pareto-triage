#!/usr/bin/env python3
"""Fail when a rule stops firing on a fixture without anyone noticing.

`detect` prints per-rule incidence, but nothing compared that output across
commits. A rule narrowed by a refactor, or a detector silently skipped, turned
a fired finding into a zero with the suite still green. This runs the real
pipeline on two fixtures that carry one planted hit per rule and compares the
counts to a checked-in golden file.

Standard library only: the guard must work wherever Python does.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CLI = HERE / "pareto-triage.py"
FIXTURES = ROOT / "fixtures"
GOLDEN = HERE / "test" / "golden" / "rule-incidence.json"
CASES = ("jvm-rules", "express-app")


def counts(fixture):
    """Per-rule hit counts from a real gate + detect run."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        for command in (
            ["gate", str(FIXTURES / fixture), "--min-loc", "1", "--out", str(out)],
            ["detect", str(FIXTURES / fixture), "--out", str(out)],
        ):
            result = subprocess.run([sys.executable, str(CLI)] + command,
                                    capture_output=True, text=True)
            if result.returncode != 0:
                raise SystemExit("%s failed on %s:\n%s%s"
                                 % (command[0], fixture, result.stdout, result.stderr))
        scope = json.loads((out / "scope.json").read_text(encoding="utf-8"))
        if "rule_incidence" not in scope:
            raise SystemExit("detect did not record rule_incidence in scope.json")
        return scope["rule_incidence"]


def differences(expected, actual):
    """Human-readable changes, one line per rule that moved or disappeared."""
    lines = []
    for rule in sorted(set(expected) | set(actual)):
        if rule not in actual:
            lines.append("%s: %d hits -> rule did not run" % (rule, expected[rule]))
        elif rule not in expected:
            lines.append("%s: new rule, %d hits" % (rule, actual[rule]))
        elif expected[rule] != actual[rule]:
            lines.append("%s: %d hits -> %d hits" % (rule, expected[rule], actual[rule]))
    return lines


def main(argv):
    write = "--write" in argv
    observed = {fixture: counts(fixture) for fixture in CASES}

    if write:
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(observed, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8")
        print("wrote %s" % GOLDEN)
        return 0

    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    failed = False
    for fixture in CASES:
        lines = differences(expected.get(fixture, {}), observed[fixture])
        if not lines:
            print("%-12s %d rules match the golden file" % (fixture, len(observed[fixture])))
            continue
        failed = True
        print("%-12s changed since %s:" % (fixture, GOLDEN.name), file=sys.stderr)
        for line in lines:
            print("  %s" % line, file=sys.stderr)
    if failed:
        print("A rule that silently stops firing is a regression. If the change is "
              "intended, re-run with --write and explain it in the commit.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
