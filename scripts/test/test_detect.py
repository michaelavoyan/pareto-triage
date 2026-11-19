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


class TestFileSkipTests(unittest.TestCase):
    """detect and context share is_test_path: test code is not scanned."""

    def test_a_reachable_test_file_is_not_scanned(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            leaky = repo / "app" / "src" / "test" / "java" / "LeakyTest.java"
            leaky.parent.mkdir(parents=True)
            leaky.write_text(
                "package com.acme;\n\npublic final class LeakyTest {\n"
                "    public Process run(String path) throws java.io.IOException {\n"
                '        return Runtime.getRuntime().exec("rm " + path);\n'
                "    }\n}\n")
            app = repo / "app" / "src" / "main" / "java" / "App.java"
            app.parent.mkdir(parents=True)
            app.write_text(
                "package com.acme;\n\npublic final class App {\n"
                "    public static void main(String[] args) {\n        run();\n    }\n\n"
                "    static void run() throws java.io.IOException {\n"
                '        Runtime.getRuntime().exec("rm " + args);\n'
                "    }\n}\n")
            out = Path(tmp) / "out"
            gate = run(["gate", repo, "--min-loc", "1", "--out", out])
            self.assertEqual(gate.returncode, 0, gate.stdout + gate.stderr)

            # A gate-produced scope never names a test file as an entrypoint.
            # Write one by hand so the test file is reachable for certainty.
            scope = json.loads((out / "scope.json").read_text())
            scope["entrypoints"].append({
                "kind": "cli", "framework": "java",
                "file": "app/src/test/java/LeakyTest.java", "line": 1, "detail": "main"})
            (out / "scope.json").write_text(json.dumps(scope), encoding="utf-8")

            result = run(["detect", repo, "--out", out])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            findings = [json.loads(line) for line in
                        (out / "defects.jsonl").read_text().splitlines() if line]
            self.assertEqual([(f["file"], f["rule"]) for f in findings],
                             [("app/src/main/java/App.java", "jvm-exec-injection")])
            self.assertIn("1 skipped as test code", result.stdout)

    def test_the_skip_count_is_printed_even_when_no_test_files_exist(self):
        with tempfile.TemporaryDirectory() as out:
            gate = run(["gate", FIXTURES / "python-app", "--min-loc", "5", "--out", out])
            self.assertEqual(gate.returncode, 0, gate.stdout + gate.stderr)
            result = run(["detect", FIXTURES / "python-app", "--out", out])
            self.assertIn("0 skipped as test code", result.stdout)


class RuleCoverageTests(unittest.TestCase):
    """A language with no detector must be reported, never implied clean."""

    @staticmethod
    def count(fixture, suffix):
        return sum(1 for p in (FIXTURES / fixture).rglob("*" + suffix)
                   if p.is_file() and "out" not in p.parts)

    def test_swift_fixture_names_the_files_no_rule_could_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            gate = run(["gate", FIXTURES / "ios-app", "--min-loc", "1", "--out", out])
            self.assertEqual(gate.returncode, 0, gate.stdout + gate.stderr)
            detect = run(["detect", FIXTURES / "ios-app", "--out", out])
            self.assertEqual(detect.returncode, 0, detect.stdout + detect.stderr)

            swift = self.count("ios-app", ".swift")
            objc = self.count("ios-app", ".m")
            self.assertIn("no rules were applied to %d files of Swift" % swift, detect.stdout)
            self.assertIn("no rules were applied to %d files of Objective-C" % objc, detect.stdout)
            self.assertIn("warning", detect.stdout)
            self.assertIn("0/%d files (no rules)" % swift, detect.stdout)

            scope = json.loads((out / "scope.json").read_text())
            rows = {row["lang"]: row for row in scope["rule_coverage"]["by_language"]}
            self.assertEqual(rows["swift"]["files"], swift)
            self.assertEqual(rows["swift"]["files_with_rules"], 0)
            self.assertEqual(rows["swift"]["rules"], [])
            self.assertEqual(rows["objc"]["files_with_rules"], 0)

    def test_a_language_with_rules_gets_no_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            gate = run(["gate", FIXTURES / "python-app", "--min-loc", "5", "--out", out])
            self.assertEqual(gate.returncode, 0, gate.stdout + gate.stderr)
            detect = run(["detect", FIXTURES / "python-app", "--out", out])
            self.assertEqual(detect.returncode, 0, detect.stdout + detect.stderr)

            self.assertNotIn("no rules were applied", detect.stdout)
            scope = json.loads((out / "scope.json").read_text())
            rows = {row["lang"]: row for row in scope["rule_coverage"]["by_language"]}
            self.assertEqual(rows["python"]["files_with_rules"], rows["python"]["files"])
            self.assertIn("py-eval", rows["python"]["rules"])


if __name__ == "__main__":
    unittest.main()
