"""The rule-count guard: a rule that stops firing must fail before merge.

This runs the same script CI runs. A golden file is only useful if a local
`unittest` run notices when it drifts.
"""

import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
CHECK = SCRIPTS / "check_rule_counts.py"


class GoldenRuleCountTests(unittest.TestCase):
    def test_fixture_counts_match_the_golden_file(self):
        result = subprocess.run([sys.executable, str(CHECK)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("rules match the golden file", result.stdout)


if __name__ == "__main__":
    unittest.main()
