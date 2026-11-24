"""F1: rule incidence is a scan artifact, not only a stdout line.

`scope.json` is written by `gate` and completed by `detect`; `ranked.json`
carries the same mapping forward so the report appendix and a published run
can be audited without re-running the scanner.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
CLI = HERE.parent / "pareto-triage.py"
FIXTURES = HERE.parent.parent / "fixtures"


def run(args):
    return subprocess.run([sys.executable, str(CLI)] + [str(a) for a in args],
                          capture_output=True, text=True)


class ScopeEvidence(unittest.TestCase):
    def test_scope_and_ranked_carry_per_rule_hits(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            for command in (["gate", FIXTURES / "express-app", "--min-loc", "1", "--out", out],
                            ["context", FIXTURES / "express-app", "--out", out],
                            ["detect", FIXTURES / "express-app", "--out", out],
                            ["rank", FIXTURES / "express-app", "--out", out]):
                result = run(command)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            scope = json.loads((out / "scope.json").read_text())
            ranked = json.loads((out / "ranked.json").read_text())
        self.assertEqual(scope["rule_incidence"]["js-sql-template"], 3)
        self.assertEqual(ranked["rule_incidence"], scope["rule_incidence"])
        # A rule that ran and found nothing is present at zero, not absent.
        self.assertEqual(ranked["rule_incidence"]["js-new-function"], 0)


if __name__ == "__main__":
    unittest.main()
