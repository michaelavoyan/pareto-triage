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

sys.path.insert(0, str(SCRIPTS))
from lib.schema import apply_confidence_cap  # noqa: E402


def run(args):
    return subprocess.run([sys.executable, str(CLI)] + [str(a) for a in args],
                          capture_output=True, text=True)


class CapUnitTests(unittest.TestCase):
    def test_downgrades_and_records_why(self):
        finding = {"confidence": "high"}
        self.assertTrue(apply_confidence_cap(finding, "med", "no test runner detected"))
        self.assertEqual(finding["confidence"], "med")
        self.assertTrue(finding["confidence_capped"])
        self.assertEqual(finding["confidence_reason"], "no test runner detected")

    def test_leaves_lower_confidence_alone(self):
        finding = {"confidence": "low"}
        self.assertFalse(apply_confidence_cap(finding, "med"))
        self.assertEqual(finding["confidence"], "low")
        self.assertNotIn("confidence_capped", finding)

    def test_no_cap_is_a_noop(self):
        finding = {"confidence": "high"}
        self.assertFalse(apply_confidence_cap(finding, None))
        self.assertEqual(finding["confidence"], "high")


class CapPipelineTests(unittest.TestCase):
    def make_repo(self, tmp, with_tests):
        repo = Path(tmp) / "repo"
        repo.mkdir(parents=True)
        (repo / "app.py").write_text(
            "import subprocess\n\n\n"
            "def run(cmd):\n    return subprocess.call(cmd, shell=True)\n\n\n"
            "if __name__ == '__main__':\n    run('ls')\n")
        if with_tests:
            (repo / "requirements.txt").write_text("pytest==8.0.0\n")
        return repo

    def test_detect_caps_when_no_test_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp, with_tests=False)
            out = Path(tmp) / "out"
            gate = run(["gate", repo, "--min-loc", "1", "--out", out])
            self.assertEqual(gate.returncode, 0, gate.stdout + gate.stderr)
            result = run(["detect", repo, "--out", out])
            self.assertEqual(result.returncode, 0, result.stderr)
            findings = [json.loads(line) for line in
                        (out / "defects.jsonl").read_text().splitlines() if line.strip()]
            self.assertTrue(findings)
            for finding in findings:
                self.assertNotEqual(finding["confidence"], "high")
                self.assertTrue(finding["confidence_capped"])

    def test_detect_keeps_high_confidence_when_tests_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp, with_tests=True)
            out = Path(tmp) / "out"
            run(["gate", repo, "--min-loc", "1", "--out", out])
            run(["detect", repo, "--out", out])
            findings = [json.loads(line) for line in
                        (out / "defects.jsonl").read_text().splitlines() if line.strip()]
            self.assertEqual({f["confidence"] for f in findings}, {"high"})

    def test_rank_records_the_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            run(["gate", FIXTURES / "express-app", "--min-loc", "1", "--out", out])
            run(["detect", FIXTURES / "express-app", "--out", out])
            run(["rank", FIXTURES / "express-app", "--out", out])
            ranked = json.loads((out / "ranked.json").read_text())
            self.assertIn("confidence_cap", ranked)

    def test_validate_rejects_confidence_above_the_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "defects.jsonl"
            path.write_text(json.dumps({
                "id": "d_1", "class": "defect", "rule": "js-eval", "taxonomy": "code-injection",
                "file": "src/unsafe.ts", "line": 2, "evidence": "return eval(source)",
                "message": "eval", "detector": "tool", "confidence": "high",
                "reach": 5, "blast": 5, "silence": 2,
            }) + "\n")
            result = run(["validate", path, "--repo", FIXTURES / "express-app",
                          "--max-confidence", "med"])
            self.assertEqual(result.returncode, 1)
            self.assertIn("exceeds the cap", result.stdout)


if __name__ == "__main__":
    unittest.main()
