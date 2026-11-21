import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
ROOT = SCRIPTS.parent

sys.path.insert(0, str(SCRIPTS))
from lib.rules import JVM_RULE_IDS, META  # noqa: E402
from lib.schema import DEFECT_TAXONOMIES, TAXONOMIES  # noqa: E402

NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def claimed_count(pattern, text, label):
    match = re.search(pattern, text)
    if match is None:
        raise AssertionError("%s no longer states a rule count" % label)
    word = match.group(1).lower()
    return int(word) if word.isdigit() else NUMBER_WORDS[word]


class DocDriftTests(unittest.TestCase):
    """The documents are the specification; a table that drifts is a bug."""

    def test_every_rule_is_documented(self):
        text = (ROOT / "references" / "defect-rules.md").read_text(encoding="utf-8")
        documented = {rule for rule in META if "`%s`" % rule in text}
        self.assertEqual(documented, set(META),
                         "rules missing from defect-rules.md: %s" % sorted(set(META) - documented))

    def test_active_rule_table_matches_meta(self):
        text = (ROOT / "references" / "defect-rules.md").read_text(encoding="utf-8")
        active, _, rejected = text.partition("## Considered and rejected")
        rows = set(re.findall(r"^\| `([a-z0-9-]+)` \|", active, re.M))
        self.assertEqual(rows, set(META),
                         "active rule table disagrees with META: missing %s, extra %s"
                         % (sorted(set(META) - rows), sorted(rows - set(META))))
        rejected_rules = set(re.findall(r"^### `([a-z0-9-]+)`", rejected, re.M))
        self.assertEqual(rejected_rules & set(META), set(),
                         "a rule is listed as active and rejected: %s"
                         % sorted(rejected_rules & set(META)))

    def test_documents_state_the_real_rule_counts(self):
        total = len(META)
        jvm = len([rule for rule in META if rule.startswith("jvm-")])
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        rules_doc = (ROOT / "references" / "defect-rules.md").read_text(encoding="utf-8")
        self.assertEqual(claimed_count(r"(\w+) rules catch", readme, "README.md"), total)
        self.assertEqual(claimed_count(r"(\w+) JVM rules", readme, "README.md"), jvm)
        self.assertEqual(claimed_count(r"`detect` runs (\w+) built-in rules",
                                       skill, "SKILL.md"), total)
        self.assertEqual(claimed_count(r"the (\w+) built-in rules", skill, "SKILL.md"), total)
        self.assertEqual(claimed_count(r"all (\w+) active rules", rules_doc,
                                       "defect-rules.md"), total)

    def test_defect_taxonomies_are_the_taxonomies_rules_emit(self):
        emitted = {axes[0] for axes in META.values()}
        self.assertEqual(set(DEFECT_TAXONOMIES), emitted,
                         "DEFECT_TAXONOMIES disagrees with the rules: unused %s, missing %s"
                         % (sorted(set(DEFECT_TAXONOMIES) - emitted),
                            sorted(emitted - set(DEFECT_TAXONOMIES))))

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
