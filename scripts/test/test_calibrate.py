import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
CLI = SCRIPTS / "pareto-triage.py"

sys.path.insert(0, str(SCRIPTS))
from lib import calibrate  # noqa: E402


def run(args):
    return subprocess.run([sys.executable, str(CLI)] + [str(a) for a in args],
                          capture_output=True, text=True)


def finding(i, taxonomy="missing-timeout"):
    return {"id": "f_%03d" % i, "class": "failure-mode", "taxonomy": taxonomy,
            "file": "a.py", "line": i, "evidence": "x", "confidence": "med"}


class SampleTests(unittest.TestCase):
    def test_sample_is_deterministic_for_a_seed(self):
        findings = [finding(i, "t%d" % (i % 4)) for i in range(60)]
        first = [f["id"] for f in calibrate.sample(findings, 20, "repo", 7)]
        second = [f["id"] for f in calibrate.sample(findings, 20, "repo", 7)]
        self.assertEqual(first, second)

    def test_different_seed_changes_the_sample(self):
        findings = [finding(i) for i in range(60)]
        self.assertNotEqual([f["id"] for f in calibrate.sample(findings, 20, "r", 1)],
                            [f["id"] for f in calibrate.sample(findings, 20, "r", 2)])

    def test_sample_is_stratified(self):
        findings = ([finding(i, "a") for i in range(30)] +
                    [finding(100 + i, "b") for i in range(10)])
        picked = calibrate.sample(findings, 10, "r", 0)
        self.assertEqual({f["taxonomy"] for f in picked}, {"a", "b"})

    def test_sample_never_exceeds_available(self):
        self.assertEqual(len(calibrate.sample([finding(1)], 20, "r", 0)), 1)


class SummaryTests(unittest.TestCase):
    def rows(self, verdicts):
        return [{"id": "f_%d" % i, "taxonomy": "missing-timeout", "verdict": v}
                for i, v in enumerate(verdicts)]

    def test_unfilled_sample_is_incomplete_not_zero(self):
        summary = calibrate.summarise(self.rows([None] * 5))
        self.assertEqual(summary["status"], "incomplete")
        self.assertIsNone(summary["precision"])

    def test_precision_above_threshold_passes(self):
        summary = calibrate.summarise(self.rows([True] * 18 + [False] * 2))
        self.assertEqual(summary["status"], "pass")
        self.assertEqual(summary["precision"], 0.9)

    def test_precision_below_threshold_fails(self):
        summary = calibrate.summarise(self.rows([True] * 10 + [False] * 10))
        self.assertEqual(summary["status"], "fail")
        self.assertIn("tune the prompt", summary["note"])

    def test_verdicts_accept_words_and_booleans(self):
        records, bad = calibrate.read_verdicts(
            '{"id":"a","verdict":"yes"}\n{"id":"b","verdict":false}\n')
        self.assertEqual([r["verdict"] for r in records], [True, False])
        self.assertEqual(bad, [])


class CalibrateCommandTests(unittest.TestCase):
    def build(self, tmp, count=25):
        out = Path(tmp) / "out"
        out.mkdir()
        findings = []
        for i in range(count):
            findings.append({"id": "f_%03d" % i, "class": "failure-mode",
                             "taxonomy": "missing-timeout", "file": "a.py", "line": i + 1,
                             "evidence": "x", "impact": 3.0, "priority": 3.0})
        (out / "ranked.json").write_text(json.dumps({
            "repo_name": "r", "prompt": {"hash": "abc"},
            "findings": findings, "clusters": []}))
        return out

    def test_writes_a_sample_then_reports_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.build(tmp)
            result = run(["calibrate", Path(tmp), "--out", out])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(len((out / "calibration.jsonl").read_text().splitlines()), 20)
            summary = json.loads((out / "calibration.json").read_text())
            self.assertEqual(summary["status"], "incomplete")
            self.assertIn("fill in each verdict", result.stdout)

    def test_filled_sample_produces_a_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.build(tmp)
            run(["calibrate", Path(tmp), "--out", out])
            rows = [json.loads(line) for line in
                    (out / "calibration.jsonl").read_text().splitlines()]
            for i, row in enumerate(rows):
                row["verdict"] = i < 18
            (out / "calibration.jsonl").write_text(
                "".join(json.dumps(r) + "\n" for r in rows))
            result = run(["calibrate", Path(tmp), "--out", out])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            summary = json.loads((out / "calibration.json").read_text())
            self.assertEqual(summary["status"], "pass")
            self.assertEqual(summary["precision"], 0.9)

    def test_bad_precision_exits_non_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.build(tmp)
            run(["calibrate", Path(tmp), "--out", out])
            rows = [json.loads(line) for line in
                    (out / "calibration.jsonl").read_text().splitlines()]
            for i, row in enumerate(rows):
                row["verdict"] = i < 5
            (out / "calibration.jsonl").write_text(
                "".join(json.dumps(r) + "\n" for r in rows))
            result = run(["calibrate", Path(tmp), "--out", out])
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads((out / "calibration.json").read_text())["status"], "fail")

    def test_no_failure_modes_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            out.mkdir()
            (out / "ranked.json").write_text(json.dumps({"repo_name": "r", "findings": []}))
            result = run(["calibrate", Path(tmp), "--out", out])
            self.assertEqual(result.returncode, 1)
            self.assertIn("calibration judges phase 2 only", result.stderr)


if __name__ == "__main__":
    unittest.main()
