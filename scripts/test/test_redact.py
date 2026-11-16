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
from lib.redact import redact, redact_findings  # noqa: E402
from lib.rules import detect_defects  # noqa: E402


def run(args):
    return subprocess.run([sys.executable, str(CLI)] + [str(a) for a in args],
                          capture_output=True, text=True)


class RedactUnitTests(unittest.TestCase):
    def test_aws_key_is_masked(self):
        masked, rules = redact("key = AKIAIOSFODNN7EXAMPLE")
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", masked)
        self.assertEqual(rules[0]["rule"], "aws-access-key")

    def test_stripe_key_is_masked(self):
        masked, _ = redact("sk_live_abcdef123456")
        self.assertNotIn("abcdef123456", masked)

    def test_private_key_block_is_masked(self):
        text = "-----BEGIN RSA PRIVATE KEY-----\nAAAA\n-----END RSA PRIVATE KEY-----"
        masked, rules = redact(text)
        self.assertNotIn("AAAA", masked)
        self.assertEqual(rules[0]["rule"], "private-key-block")

    def test_unquoted_assignment_is_masked(self):
        masked, _ = redact("DB_PASSWORD=hunter2hunter2")
        self.assertEqual(masked, "DB_PASSWORD=" + "\u2022" * 8)

    def test_quoted_assignment_keeps_the_quotes(self):
        masked, _ = redact('password: "s3cr3tvalue"')
        self.assertEqual(masked, 'password: "' + "\u2022" * 8 + '"')

    def test_code_references_are_left_alone(self):
        for text in ("const token = process.env.TOKEN",
                     "password: process.env.PASS",
                     "token = ${SECRET_TOKEN}",
                     "return eval(source)"):
            masked, rules = redact(text)
            self.assertEqual(masked, text)
            self.assertEqual(rules, [])

    def test_redaction_is_idempotent(self):
        once, _ = redact('password: "s3cr3tvalue"')
        twice, _ = redact(once)
        self.assertEqual(once, twice)

    def test_findings_report_each_redaction(self):
        findings = [
            {"file": ".env", "line": 1, "evidence": "KEY=AKIAIOSFODNN7EXAMPLE"},
            {"file": "a.py", "line": 2, "evidence": "return eval(source)"},
        ]
        redactions = redact_findings(findings)
        self.assertEqual(len(redactions), 1)
        self.assertEqual(redactions[0]["file"], ".env")
        self.assertTrue(findings[0]["redacted"])
        self.assertNotIn("redacted", findings[1])


class DetectionScopeTests(unittest.TestCase):
    def test_dotenv_is_scanned(self):
        findings, _ = detect_defects([{
            "rel": ".env", "ext": "",
            "text": "AWS_KEY=AKIAIOSFODNN7EXAMPLE\nDB_PASSWORD=hunter2hunter2\n"}])
        rules = {f["rule"] for f in findings}
        self.assertEqual(rules, {"py-secret-aws", "cfg-secret-generic"})

    def test_yaml_credentials_are_scanned(self):
        findings, _ = detect_defects([{
            "rel": "config/app.yaml", "ext": ".yaml",
            "text": "db:\n  password: \"s3cr3tvalue\"\n"}])
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["rule"], "cfg-secret-generic")

    def test_python_secrets_are_scanned(self):
        findings, _ = detect_defects([{
            "rel": "settings.py", "ext": ".py",
            "text": "AWS = 'AKIAIOSFODNN7EXAMPLE'\n"}])
        self.assertEqual({f["rule"] for f in findings}, {"py-secret-aws"})

    def test_unrelated_files_are_not_scanned(self):
        findings, _ = detect_defects([{
            "rel": "notes.md", "ext": ".md",
            "text": "AWS_KEY=AKIAIOSFODNN7EXAMPLE\n"}])
        self.assertEqual(findings, [])


class PublishTests(unittest.TestCase):
    def make_repo(self, tmp):
        repo = Path(tmp) / "repo"
        (repo / "src").mkdir(parents=True)
        (repo / ".env").write_text(
            "AWS_KEY=AKIAIOSFODNN7EXAMPLE\nDB_PASSWORD=hunter2hunter2\n")
        (repo / "src" / "app.py").write_text(
            "import subprocess\n\n\n"
            "def run(cmd):\n    return subprocess.call(cmd, shell=True)\n\n\n"
            "if __name__ == '__main__':\n    run('ls')\n")
        return repo

    def test_published_artifacts_carry_no_secret_but_the_raw_artifact_does(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            out = Path(tmp) / "out"
            for command in (["gate", repo, "--min-loc", "1", "--out", out],
                            ["detect", repo, "--out", out],
                            ["rank", repo, "--out", out]):
                result = run(command)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            result = run(["report", repo, "--out", out])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("redacted", result.stdout)

            self.assertIn("AKIAIOSFODNN7EXAMPLE", (out / "defects.jsonl").read_text())
            published = (out / "report.json").read_text()
            html = (out / "report.html").read_text()
            for artifact in (published, html):
                self.assertNotIn("AKIAIOSFODNN7EXAMPLE", artifact)
                self.assertNotIn("hunter2hunter2", artifact)

            report = json.loads(published)
            self.assertTrue(report["redactions"])
            self.assertIn("out/defects.jsonl", html)


if __name__ == "__main__":
    unittest.main()
