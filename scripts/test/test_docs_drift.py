import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
ROOT = SCRIPTS.parent

sys.path.insert(0, str(SCRIPTS))
from lib.rules import META  # noqa: E402
from lib.schema import TAXONOMIES  # noqa: E402


class DocDriftTests(unittest.TestCase):
    """The documents are the specification; a table that drifts is a bug."""

    def test_every_rule_is_documented(self):
        text = (ROOT / "references" / "defect-rules.md").read_text(encoding="utf-8")
        documented = {rule for rule in META if "`%s`" % rule in text}
        self.assertEqual(documented, set(META),
                         "rules missing from defect-rules.md: %s" % sorted(set(META) - documented))

    def test_every_taxonomy_is_documented(self):
        text = (ROOT / "references" / "taxonomy.md").read_text(encoding="utf-8")
        headings = re.findall(r"^## \d+\. ([a-z-]+)$", text, re.M)
        self.assertEqual(set(headings), set(TAXONOMIES),
                         "taxonomy headings disagree with schema.py")

    def test_taxonomy_claims_match_its_section_count(self):
        text = (ROOT / "references" / "taxonomy.md").read_text(encoding="utf-8")
        headings = re.findall(r"^## \d+\. ([a-z-]+)$", text, re.M)
        claimed = re.search(r"(Thirteen|[A-Z][a-z]+) categories", text)
        self.assertIsNotNone(claimed, "taxonomy.md no longer states a count")
        self.assertEqual(claimed.group(0).split()[0].lower(), "thirteen")
        self.assertEqual(len(headings), 13)


if __name__ == "__main__":
    unittest.main()
