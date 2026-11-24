"""`js-unvalidated-input` was withdrawn; its fixtures stay silent.

The rule produced 0 findings on JobPilot and Signal-Android, so incidence was
zero on both corpora and there was no hit to measure. The firing and silent
shapes remain as fixtures: a future proposal has to make this test fail before
it can ship, and the review of the shape starts from the measurement in
references/defect-rules.md.
"""

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
FIXTURES = SCRIPTS.parent / "fixtures" / "express-app"

sys.path.insert(0, str(SCRIPTS))
from lib.rules import META, detect_defects  # noqa: E402


class WithdrawnUnvalidatedInputTests(unittest.TestCase):
    def detect(self, names):
        files = [{"rel": "src/%s" % name, "ext": ".ts",
                  "text": (FIXTURES / "src" / name).read_text(encoding="utf-8")}
                 for name in names]
        findings, _ = detect_defects(files)
        return findings

    def test_the_rule_is_not_shipped(self):
        self.assertNotIn("js-unvalidated-input", META)

    def test_the_firing_and_validated_shapes_produce_no_finding(self):
        self.assertEqual(self.detect(["unvalidated.ts", "validated.ts"]), [])


if __name__ == "__main__":
    unittest.main()
