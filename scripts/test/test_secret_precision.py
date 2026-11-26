"""Secret precision: sample files and structurally placeholder values are silent."""

import json
import posixpath
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
CLI = SCRIPTS / "pareto-triage.py"
FIXTURES = SCRIPTS.parent / "fixtures"
SAMPLE_FIXTURE = FIXTURES / "secret-precision"

sys.path.insert(0, str(SCRIPTS))
from lib.rules import detect_defects, is_placeholder_path  # noqa: E402


def run(args):
    return subprocess.run([sys.executable, str(CLI)] + [str(a) for a in args],
                          capture_output=True, text=True)


def source(rel, text):
    return {"rel": rel, "ext": posixpath.splitext(rel)[1], "text": text}


def rules(rel, text):
    findings, _ = detect_defects([source(rel, text)])
    return [finding["rule"] for finding in findings]


REAL_PEM_BODY = (
    "k3Jd9fQ2mZ7pLx4Rt8Yb1Nc6Wv0Hs5AgE2uDq7Fi9Kd4Mf8Pz2Xw7Lc1Vr6Tn3Bj5Gh0Sq9Ue4Ay8Di2Ok7Wm1Zp"
    "R4tY6uI8oP0aS2dF4gH6jK8lZ1xC3vB5nM7qW9eR2tY4uI6oP8aS0dF2gH4jK6lZ")


def pem(body=REAL_PEM_BODY):
    return ("key: |\n"
            "  -----BEGIN PRIVATE KEY-----\n"
            "  %s\n"
            "  -----END PRIVATE KEY-----\n" % body)


class PlaceholderPathTests(unittest.TestCase):
    def test_sample_names_are_recognised_in_any_path_segment(self):
        for rel in ("service/config/sample.yml",
                    "service/config/sample-secrets-bundle.yml",
                    "examples/prod.yml",
                    "config/app.template.yaml",
                    "deploy/config.tmpl",
                    "deploy/config.dist",
                    "deploy/config.example",
                    "config/placeholder.yaml"):
            self.assertTrue(is_placeholder_path(rel), rel)

    def test_a_real_config_path_is_not_a_placeholder(self):
        for rel in ("service/config/main.yml", "src/settings.py",
                    "config/app.yaml"):
            self.assertFalse(is_placeholder_path(rel), rel)


class PlaceholderValueTests(unittest.TestCase):
    """Every listed shape must be silent in a non-sample file."""

    def assert_silent(self, text, rel="config/app.yaml"):
        self.assertEqual(rules(rel, text), [], text)

    def test_secret_uri_is_silent(self):
        self.assert_silent('db_password: secret://db.password\n')

    def test_one_repeated_character_is_silent(self):
        for value in ("AAAAAAAAAAAAAAAA", "xxxxxxxxxxxx", "000000000000"):
            self.assert_silent("api_key: %s\n" % value)

    def test_sequential_alphabet_and_digits_are_silent(self):
        for value in ("abcdefghijklmnopqrstuvwxyz",
                      "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
                      "01234567890123456789"):
            self.assert_silent("api_key: %s\n" % value)

    def test_trailing_ellipsis_is_silent(self):
        for value in ("abc123...", "abc123…"):
            self.assert_silent("api_key: %s\n" % value)

    def test_angle_bracket_and_interpolation_are_silent(self):
        for value in ("<your-api-key-here>", "${API_KEY}"):
            self.assert_silent("api_key: %s\n" % value)

    def test_short_pem_body_is_silent(self):
        self.assert_silent(
            "key: |\n"
            "  -----BEGIN PRIVATE KEY-----\n"
            "  MIIBOgIBAAJBAK\n"
            "  -----END PRIVATE KEY-----\n")

    def test_pem_filler_is_silent(self):
        for body in ("A" * 160, "ABCDEFGHIJKLMNOPQRSTUVWXYZ" * 8,
                     "placeholder" * 16):
            self.assert_silent(pem(body))

    def test_sequential_aws_and_stripe_values_are_silent(self):
        self.assertEqual(rules("src/settings.py",
                               'AWS = "AKIAABCDEFGHIJKLMNOP"\n'), [])
        self.assertEqual(rules("src/settings.py",
                               'STRIPE = "sk_live_abcdefghijklmnop"\n'), [])


class RealisticSecretTests(unittest.TestCase):
    """The narrowing must not swallow values a maintainer would call real."""

    def test_a_realistic_aws_access_key_still_fires(self):
        self.assertEqual(rules("src/settings.py",
                               'AWS = "AKIAZ3P7Q2N5R8T1V4W6"\n'),
                         ["py-secret-aws"])

    def test_a_realistic_40_char_base64_secret_still_fires(self):
        self.assertEqual(
            rules("config/app.yaml",
                  "aws_secret_access_key: wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY\n"),
            ["cfg-secret-generic"])

    def test_a_full_length_pem_body_still_fires(self):
        self.assertEqual(rules("config/app.yaml", pem()), ["py-secret-pem"])

    def test_a_realistic_live_stripe_key_still_fires(self):
        # Split so the repository never carries a contiguous live-key literal:
        # GitHub push protection treats one as a real Stripe credential.
        stripe = "sk_" + "live_" + "51H8xQ2eZvKYlo2C9mN4pR7tW"
        self.assertEqual(
            rules("src/settings.py", 'STRIPE = "%s"\n' % stripe),
            ["py-secret-stripe"])


class SampleFileTests(unittest.TestCase):
    def test_every_sample_path_shape_skips_a_realistic_value(self):
        text = "aws_secret_access_key: wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY\n"
        for rel in ("config/sample-secrets.yml",
                    "config/example-secrets.yml",
                    "config/template-secrets.yml",
                    "config/placeholder-secrets.yml",
                    "config/app.tmpl",
                    "config/app.dist",
                    "config/app.example",
                    "examples/app.yml"):
            self.assertEqual(rules(rel, text), [], rel)

    def test_the_sample_fixture_yields_no_findings(self):
        text = (SAMPLE_FIXTURE / "config" / "sample-secrets.yml").read_text(encoding="utf-8")
        self.assertEqual(rules("config/sample-secrets.yml", text), [])

    def test_detect_skips_the_sample_file_and_records_the_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            shutil.copytree(SAMPLE_FIXTURE, repo)
            out = Path(tmp) / "out"

            gate = run(["gate", repo, "--min-loc", "1", "--out", out])
            self.assertEqual(gate.returncode, 0, gate.stdout + gate.stderr)
            detect = run(["detect", repo, "--out", out])
            self.assertEqual(detect.returncode, 0, detect.stdout + detect.stderr)

            findings = [json.loads(line) for line in
                        (out / "defects.jsonl").read_text(encoding="utf-8").splitlines() if line]
            scope = json.loads((out / "scope.json").read_text(encoding="utf-8"))

        self.assertEqual(findings, [])
        self.assertIn("1 placeholder file skipped", detect.stdout)
        # Not a git repository: the wider scope must be stated, not implied.
        self.assertIn("secret scanning covers every config file, not tracked ones", detect.stdout)
        self.assertIn("every config file", detect.stdout)
        self.assertEqual(scope["secrets"]["covers"], "every config file")
        self.assertEqual(scope["secrets"]["placeholder_files_skipped"], 1)
        self.assertEqual(scope["secrets"]["placeholder_files"],
                         ["config/sample-secrets.yml"])


class BlockingSecurityTests(unittest.TestCase):
    def test_weak_hash_ranks_but_never_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            gate = run(["gate", FIXTURES / "jvm-rules", "--min-loc", "1", "--out", out])
            self.assertEqual(gate.returncode, 0, gate.stdout + gate.stderr)
            detect = run(["detect", FIXTURES / "jvm-rules", "--out", out])
            self.assertEqual(detect.returncode, 0, detect.stdout + detect.stderr)
            result = run(["rank", FIXTURES / "jvm-rules", "--out", out])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            ranked = json.loads((out / "ranked.json").read_text(encoding="utf-8"))

        self.assertIn("weak-hash", {finding["taxonomy"] for finding in ranked["findings"]})
        self.assertNotIn("jvm-weak-hash", ranked["blocking_security"])


if __name__ == "__main__":
    unittest.main()
