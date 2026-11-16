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
from lib import probes  # noqa: E402
from lib.verify import resolve_runner  # noqa: E402


def run(args):
    return subprocess.run([sys.executable, str(CLI)] + [str(a) for a in args],
                          capture_output=True, text=True)


class TemplateTests(unittest.TestCase):
    def test_every_failure_mode_has_a_template(self):
        found = probes.templates()
        self.assertEqual(len(found), 13)
        for taxonomy in ("missing-timeout", "missing-idempotency", "missing-cancellation"):
            self.assertIn(taxonomy, found)

    def test_render_fills_placeholders(self):
        body, ext = probes.render(
            "missing-timeout",
            {"key": "missing-timeout", "file": "src/a.py", "line": 12, "function": "fetch"},
            {"lang": "py"})
        self.assertEqual(ext, ".py")
        self.assertIn("src/a.py:12", body)
        self.assertIn("fetch", body)
        self.assertNotIn("{{", body)

    def test_unknown_taxonomy_has_no_template(self):
        self.assertEqual(probes.render("made-up", {}, {}), (None, None))

    def test_scaffold_is_recognised_until_edited(self):
        body, _ = probes.render("no-retry", {"key": "k"}, {"lang": "py"})
        self.assertTrue(probes.is_unfilled(body))
        self.assertFalse(probes.is_unfilled(body.replace('raise SystemExit("unfilled scaffold")',
                                                         "raise SystemExit(3)")))

    def test_missing_file_is_not_an_exception(self):
        self.assertEqual(probes.templates("/nonexistent/probes.md"), {})


class RunnerTests(unittest.TestCase):
    def test_python_uses_the_interpreter(self):
        self.assertEqual(resolve_runner("a.py", "/tmp")[0], ["python3"])

    def test_unknown_extension_is_a_named_reason(self):
        argv, reason = resolve_runner("a.rb", "/tmp")
        self.assertIsNone(argv)
        self.assertIn(".rb", reason)

    def test_typescript_without_a_runner_explains_itself(self):
        argv, reason = resolve_runner("a.ts", "/tmp/does-not-exist")
        if argv is None:
            self.assertIn("tsx", reason)


class ScaffoldPipelineTests(unittest.TestCase):
    def build(self, tmp):
        out = Path(tmp) / "out"
        for command in (["gate", FIXTURES / "express-app", "--min-loc", "1", "--out", out],
                        ["context", FIXTURES / "express-app", "--out", out],
                        ["detect", FIXTURES / "express-app", "--out", out]):
            result = run(command)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        (out / "failure-modes.jsonl").write_text(json.dumps({
            "id": "f_1", "site_id": "s_001", "class": "failure-mode",
            "taxonomy": "missing-idempotency", "file": "src/routes.ts", "line": 9,
            "evidence": "await chargeCard(event.amount)",
            "counter_evidence": "Stripe may dedupe.", "detector": "llm",
            "confidence": "med", "reach": 5, "blast": 5, "silence": 3,
        }) + "\n")
        result = run(["rank", FIXTURES / "express-app", "--out", out])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return out

    def test_scaffold_writes_one_file_and_skips_defects(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.build(tmp)
            result = run(["verify", FIXTURES / "express-app", "--out", out, "--scaffold"])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            written = list((out / "probes").iterdir())
            self.assertEqual(len(written), 1)
            self.assertIn("unfilled scaffold", written[0].read_text())
            self.assertIn("tool-proven defect", result.stdout)

    def test_unfilled_scaffold_is_never_counted_as_reproduced(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.build(tmp)
            run(["verify", FIXTURES / "express-app", "--out", out, "--scaffold"])
            result = run(["verify", FIXTURES / "express-app", "--out", out])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads((out / "verify.json").read_text())
            record = next(r for r in payload["clusters"] if r["cluster"] == "missing-idempotency")
            self.assertEqual(record["status"], "unverified")
            self.assertIn("unfilled scaffold", record["reason"])

    def test_scaffold_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.build(tmp)
            run(["verify", FIXTURES / "express-app", "--out", out, "--scaffold"])
            result = run(["verify", FIXTURES / "express-app", "--out", out, "--scaffold"])
            self.assertIn("already exists", result.stdout)


if __name__ == "__main__":
    unittest.main()
