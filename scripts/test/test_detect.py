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


def gate_and_detect(fixture, min_loc):
    tmp = tempfile.TemporaryDirectory()
    out = Path(tmp.name)
    gate = run(["gate", FIXTURES / fixture, "--min-loc", str(min_loc), "--out", out])
    assert gate.returncode == 0, gate.stdout + gate.stderr
    detect = run(["detect", FIXTURES / fixture, "--out", out])
    assert detect.returncode == 0, detect.stdout + detect.stderr
    findings = [json.loads(line) for line in (out / "defects.jsonl").read_text().splitlines() if line]
    return tmp, out, findings


class DetectTests(unittest.TestCase):
    def test_python_rules_find_the_planted_defects(self):
        tmp, out, findings = gate_and_detect("python-app", 5)
        self.addCleanup(tmp.cleanup)
        rules = {f["rule"] for f in findings}
        self.assertEqual(rules, {"py-shell-true", "py-eval", "py-mutable-default"}, rules)
        for finding in findings:
            self.assertEqual(finding["class"], "defect")
            self.assertEqual(finding["detector"], "tool")
            self.assertEqual(finding["confidence"], "high")
            self.assertEqual(finding["reach"], 5)  # same file as the routes
            self.assertEqual(finding["effort"], 1)  # pytest present, mechanical fix

    def test_js_rules_find_the_planted_defects(self):
        tmp, out, findings = gate_and_detect("express-app", 10)
        self.addCleanup(tmp.cleanup)
        rules = {f["rule"] for f in findings}
        self.assertEqual(rules, {"js-eval", "js-tls-off"}, rules)

    def test_evidence_is_verbatim(self):
        tmp, out, findings = gate_and_detect("python-app", 5)
        self.addCleanup(tmp.cleanup)
        sources = {p.relative_to(FIXTURES / "python-app").as_posix(): p.read_text()
                   for p in (FIXTURES / "python-app").rglob("*") if p.is_file()}
        squash = lambda s: " ".join(s.split())
        for finding in findings:
            self.assertIn(squash(finding["evidence"]), squash(sources[finding["file"]]))

    def test_detect_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_a = Path(tmp) / "a"
            out_b = Path(tmp) / "b"
            for out in (out_a, out_b):
                run(["gate", FIXTURES / "python-app", "--min-loc", "5", "--out", out])
                run(["detect", FIXTURES / "python-app", "--out", out])
            self.assertEqual((out_a / "defects.jsonl").read_text(),
                             (out_b / "defects.jsonl").read_text())

    def test_detect_refuses_without_scope(self):
        with tempfile.TemporaryDirectory() as out:
            result = run(["detect", FIXTURES / "python-app", "--out", out])
            self.assertEqual(result.returncode, 2)
            self.assertIn("run: pareto-triage gate", result.stderr)
            self.assertEqual(list(Path(out).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
