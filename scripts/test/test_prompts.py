import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
CLI = SCRIPTS / "pareto-triage.py"
FIXTURES = SCRIPTS.parent / "fixtures"
PROMPTS = SCRIPTS.parent / "references" / "prompts.md"

sys.path.insert(0, str(SCRIPTS))
from lib.prompts import identity  # noqa: E402


def run(args):
    return subprocess.run([sys.executable, str(CLI)] + [str(a) for a in args],
                          capture_output=True, text=True)


class IdentityTests(unittest.TestCase):
    def test_identity_is_stable_across_calls(self):
        self.assertEqual(identity(), identity())

    def test_identity_is_a_hash_and_nothing_else(self):
        found = identity()
        self.assertEqual(set(found), {"hash"})
        self.assertEqual(len(found["hash"]), 16)

    def test_trailing_whitespace_is_not_a_prompt_change(self):
        original = identity()
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "prompts.md"
            text = PROMPTS.read_text()
            copy.write_text("\n".join(line + "   " for line in text.split("\n")))
            self.assertEqual(identity(copy)["hash"], original["hash"])

    def test_a_real_edit_changes_the_hash(self):
        original = identity()
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "prompts.md"
            copy.write_text(PROMPTS.read_text().replace(
                "No evidence, no finding.", "No evidence at all, no finding."))
            self.assertNotEqual(identity(copy)["hash"], original["hash"])

    def test_missing_file_is_not_an_exception(self):
        self.assertEqual(identity("/nonexistent/prompts.md"), {"hash": None})


class ReportingTests(unittest.TestCase):
    def test_rank_records_and_report_shows_the_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            for command in (["gate", FIXTURES / "express-app", "--min-loc", "1", "--out", out],
                            ["detect", FIXTURES / "express-app", "--out", out],
                            ["rank", FIXTURES / "express-app", "--out", out]):
                result = run(command)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            ranked = json.loads((out / "ranked.json").read_text())
            self.assertEqual(ranked["prompt"], identity())

            result = run(["report", FIXTURES / "express-app", "--out", out])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            html = (out / "report.html").read_text()
            self.assertIn("prompt %s" % identity()["hash"], html)
            self.assertIn(identity()["hash"], html)


class ValidationTests(unittest.TestCase):
    def record(self, stamp=None):
        record = {
            "id": "f_1", "class": "failure-mode", "taxonomy": "missing-idempotency",
            "file": "src/routes.ts", "line": 9, "evidence": "await chargeCard(event.amount)",
            "counter_evidence": "Maybe fine.", "detector": "llm", "confidence": "med",
            "reach": 5, "blast": 5, "silence": 3,
        }
        if stamp:
            record["prompt"] = {"hash": stamp}
        return record

    def test_matching_stamp_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "failure-modes.jsonl"
            path.write_text(json.dumps(self.record(identity()["hash"])) + "\n")
            result = run(["validate", path, "--repo", FIXTURES / "express-app"])
            self.assertEqual(result.returncode, 0, result.stdout)

    def test_mismatched_stamp_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "failure-modes.jsonl"
            path.write_text(json.dumps(self.record("deadbeefdeadbeef")) + "\n")
            result = run(["validate", path, "--repo", FIXTURES / "express-app"])
            self.assertEqual(result.returncode, 1)
            self.assertIn("not comparable", result.stdout)

    def test_missing_stamp_warns_but_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "failure-modes.jsonl"
            path.write_text(json.dumps(self.record()) + "\n")
            result = run(["validate", path, "--repo", FIXTURES / "express-app"])
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn("no prompt hash", result.stdout)

    def test_rank_does_not_rank_a_foreign_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            run(["gate", FIXTURES / "express-app", "--min-loc", "1", "--out", out])
            run(["detect", FIXTURES / "express-app", "--out", out])
            (out / "failure-modes.jsonl").write_text(
                json.dumps(self.record("deadbeefdeadbeef")) + "\n")
            result = run(["rank", FIXTURES / "express-app", "--out", out])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            ranked = json.loads((out / "ranked.json").read_text())
            self.assertNotIn("f_1", {f["id"] for f in ranked["findings"]})
            self.assertEqual(len(ranked["unproven"]), 1)
            self.assertIn("different prompts", ranked["unproven"][0]["reason"])

    def test_strict_refuses_it_instead(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            run(["gate", FIXTURES / "express-app", "--min-loc", "1", "--out", out])
            run(["detect", FIXTURES / "express-app", "--out", out])
            (out / "failure-modes.jsonl").write_text(
                json.dumps(self.record("deadbeefdeadbeef")) + "\n")
            result = run(["rank", FIXTURES / "express-app", "--out", out, "--strict"])
            self.assertEqual(result.returncode, 1)
            self.assertFalse((out / "ranked.json").exists())


if __name__ == "__main__":
    unittest.main()
