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


def run(args):
    return subprocess.run([sys.executable, str(CLI)] + [str(a) for a in args],
                          capture_output=True, text=True)


def finding(site_id, file, line, evidence="await chargeCard(event.amount)"):
    return {
        "id": "f_1", "site_id": site_id, "class": "failure-mode",
        "taxonomy": "missing-idempotency", "file": file, "line": line,
        "evidence": evidence, "counter_evidence": "Maybe fine.",
        "detector": "llm", "confidence": "med", "reach": 5, "blast": 5, "silence": 3,
    }


def finding_for(site, index=1):
    first_line = next(line.strip() for line in site["source"].split("\n") if line.strip())
    record = finding(site["site_id"], site["file"], site["lines"][0], evidence=first_line)
    record["id"] = "f_%d" % index
    return record


class CoverageTests(unittest.TestCase):
    def build(self, out):
        for command in (["gate", FIXTURES / "express-app", "--min-loc", "1", "--out", out],
                        ["context", FIXTURES / "express-app", "--out", out],
                        ["detect", FIXTURES / "express-app", "--out", out]):
            result = run(command)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def sites(self, out):
        return [json.loads(line) for line in
                (Path(out) / "context.jsonl").read_text().splitlines() if line.strip()]

    def test_rank_reports_partial_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.build(out)
            site = self.sites(out)[0]
            (out / "failure-modes.jsonl").write_text(json.dumps(finding_for(site)) + "\n")
            result = run(["rank", FIXTURES / "express-app", "--out", out])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            ranked = json.loads((out / "ranked.json").read_text())
            coverage = ranked["coverage"]
            self.assertEqual(coverage["sites_total"], len(self.sites(out)))
            self.assertEqual(coverage["sites_judged"], 1)
            self.assertEqual(coverage["sites_unjudged"], coverage["sites_total"] - 1)
            self.assertIn("coverage", result.stdout)

    def test_require_coverage_refuses_a_partial_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.build(out)
            site = self.sites(out)[0]
            (out / "failure-modes.jsonl").write_text(json.dumps(finding_for(site)) + "\n")
            result = run(["rank", FIXTURES / "express-app", "--out", out,
                          "--require-coverage", "0.99"])
            self.assertEqual(result.returncode, 1)
            self.assertIn("below --require-coverage", result.stderr)
            self.assertFalse((out / "ranked.json").exists())

    def test_full_coverage_passes_the_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.build(out)
            records = [finding_for(s, i) for i, s in enumerate(self.sites(out), start=1)]
            (out / "failure-modes.jsonl").write_text(
                "".join(json.dumps(r) + "\n" for r in records))
            result = run(["rank", FIXTURES / "express-app", "--out", out,
                          "--require-coverage", "1.0"])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unknown_site_id_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.build(out)
            (out / "failure-modes.jsonl").write_text(
                json.dumps(finding("s_999", "src/routes.ts", 9)) + "\n")
            result = run(["rank", FIXTURES / "express-app", "--out", out])
            self.assertEqual(result.returncode, 1)
            self.assertIn("not in context.jsonl", result.stderr)

    def test_site_and_finding_disagreement_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.build(out)
            site = next(s for s in self.sites(out) if s["file"] == "src/billing.ts")
            (out / "failure-modes.jsonl").write_text(
                json.dumps(finding(site["site_id"], "src/routes.ts", 9)) + "\n")
            result = run(["rank", FIXTURES / "express-app", "--out", out])
            self.assertEqual(result.returncode, 1)
            self.assertIn("site", result.stderr)


class ValidateCorrespondenceTests(unittest.TestCase):
    def validate(self, record, extra=()):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "failure-modes.jsonl"
            path.write_text(json.dumps(record) + "\n")
            return run(["validate", path, "--repo", FIXTURES / "express-app",
                        "--context", FIXTURES / ".." / ".." / "x" / "nope.jsonl"] + list(extra))

    def test_line_outside_the_site_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            for command in (["gate", FIXTURES / "express-app", "--min-loc", "1", "--out", out],
                            ["context", FIXTURES / "express-app", "--out", out]):
                run(command)
            site = json.loads((out / "context.jsonl").read_text().splitlines()[0])
            path = out / "failure-modes.jsonl"
            path.write_text(json.dumps(finding(site["site_id"], site["file"],
                                               site["lines"][1] + 5)) + "\n")
            result = run(["validate", path, "--repo", FIXTURES / "express-app",
                          "--context", out / "context.jsonl"])
            self.assertEqual(result.returncode, 1)
            self.assertIn("outside site", result.stdout)

    def test_evidence_elsewhere_in_the_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            for command in (["gate", FIXTURES / "express-app", "--min-loc", "1", "--out", out],
                            ["context", FIXTURES / "express-app", "--out", out]):
                run(command)
            site = next(json.loads(line) for line in (out / "context.jsonl").read_text().splitlines()
                        if json.loads(line)["file"] == "src/routes.ts")
            # Real text, but from the route file's export line, outside the site body.
            path = out / "failure-modes.jsonl"
            path.write_text(json.dumps(finding(site["site_id"], site["file"],
                                               site["lines"][0],
                                               evidence="export { app, router }")) + "\n")
            result = run(["validate", path, "--repo", FIXTURES / "express-app",
                          "--context", out / "context.jsonl"])
            self.assertEqual(result.returncode, 1)
            self.assertIn("not inside site", result.stdout)

    def test_strict_context_without_a_file_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "failure-modes.jsonl"
            path.write_text(json.dumps(finding("s_1", "src/routes.ts", 9)) + "\n")
            result = run(["validate", path, "--repo", FIXTURES / "express-app",
                          "--context", Path(tmp) / "missing.jsonl", "--strict-context"])
            self.assertEqual(result.returncode, 2)
            self.assertIn("--strict-context", result.stderr)


if __name__ == "__main__":
    unittest.main()
