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
from lib.effort import (apply_efforts, call_profile, crosses_boundary,  # noqa: E402
                        defect_effort, failure_mode_effort, package_of,
                        reverse_importers)


def run(args):
    return subprocess.run([sys.executable, str(CLI)] + [str(a) for a in args],
                          capture_output=True, text=True)


class FormulaTests(unittest.TestCase):
    def test_defect_is_cheap_and_local_by_default(self):
        effort, drivers = defect_effort("src/a.ts", [], no_test=False)
        self.assertEqual(effort, 1)
        self.assertIn("1 file", drivers)
        self.assertIn("0 importers", drivers)

    def test_defect_pays_for_no_tests_and_a_boundary(self):
        self.assertEqual(defect_effort("src/a.ts", ["src/b.ts"], no_test=True)[0], 2)
        self.assertEqual(defect_effort("src/a.ts", ["db/b.ts"], no_test=False)[0], 2)
        self.assertEqual(defect_effort("src/a.ts", ["db/b.ts"], no_test=True)[0], 3)

    def test_defect_effort_is_clamped(self):
        effort, _ = defect_effort("a/b.ts", ["c/d.ts"], no_test=True)
        self.assertLessEqual(effort, 5)
        self.assertGreaterEqual(effort, 1)

    def test_boundary_uses_the_first_two_segments(self):
        self.assertFalse(crosses_boundary("src/a.ts", ["src/b.ts"]))
        self.assertTrue(crosses_boundary("src/api/x.ts", ["src/db/y.ts"]))
        self.assertTrue(crosses_boundary("a.ts", ["src/b.ts"]))  # root vs package

    def test_package_of_root_file_is_empty(self):
        self.assertEqual(package_of("main.ts"), "")
        self.assertEqual(package_of("src/main.ts"), "src")
        self.assertEqual(package_of("src/api/routes.ts"), "src/api")

    def test_failure_mode_uses_the_five_term_formula(self):
        profile = {"files": ["src/b.ts", "src/c.ts", "src/d.ts"], "callsites": 10}
        effort, drivers = failure_mode_effort("src/a.ts", profile, no_test=False)
        # 1 + 4 files/3 + 10 callsites/5 = 1 + 1 + 2
        self.assertEqual(effort, 4)
        self.assertIn("4 files", drivers)
        self.assertIn("10 call sites", drivers)

    def test_failure_mode_without_a_symbol_says_so(self):
        effort, drivers = failure_mode_effort("src/routes.ts", None, no_test=False)
        self.assertEqual(effort, 1)
        self.assertIn("handler has no name to count", drivers)

    def test_call_profile_excludes_the_definition(self):
        files = [
            {"rel": "src/a.ts", "ext": ".ts", "text": "function charge() {}\ncharge()\n"},
            {"rel": "src/b.ts", "ext": ".ts", "text": "import { charge } from './a'\ncharge()\n"},
            {"rel": "notes.md", "ext": ".md", "text": "charge charge charge"},
        ]
        profile = call_profile("charge", "src/a.ts", files)
        self.assertEqual(profile["files"], ["src/a.ts", "src/b.ts"])
        # One call in a.ts (definition excluded), an import mention and a call in b.ts.
        self.assertEqual(profile["callsites"], 3)

    def test_call_profile_returns_none_for_a_route_name(self):
        self.assertIsNone(call_profile("POST /webhooks/stripe", "src/routes.ts", []))

    def test_drivers_never_claim_a_hardcoded_site(self):
        _, drivers = defect_effort("src/a.ts", ["src/b.ts", "src/c.ts"], no_test=False)
        self.assertIn("2 importers", drivers)
        self.assertNotIn("1 site", drivers)


class ApplyTests(unittest.TestCase):
    def test_rank_style_derivation_covers_both_classes(self):
        files = [
            {"rel": "src/a.ts", "ext": ".ts", "text": "function charge() {}\ncharge()\n"},
            {"rel": "src/b.ts", "ext": ".ts", "text": "import { charge } from './a'\ncharge()\ncharge()\n"},
        ]
        findings = [
            {"id": "d_1", "class": "defect", "file": "src/a.ts", "line": 1},
            {"id": "f_1", "class": "failure-mode", "file": "src/a.ts", "line": 1},
        ]
        apply_efforts(findings, files, no_test=False)
        self.assertEqual(findings[0]["effort"], 1)
        self.assertGreaterEqual(findings[1]["effort"], 1)
        self.assertTrue(findings[1]["effort_drivers"])

    def test_trust_model_keeps_supplied_effort(self):
        files = [{"rel": "src/a.ts", "ext": ".ts", "text": "function f() {}\n"}]
        findings = [{"id": "f_1", "class": "failure-mode", "file": "src/a.ts", "line": 1, "effort": 4}]
        apply_efforts(findings, files, no_test=False, trust_model=True)
        self.assertEqual(findings[0]["effort"], 4)

    def test_reverse_importers_is_sorted_and_deduplicated(self):
        files = [
            {"rel": "src/a.ts", "ext": ".ts", "text": "import './b'\nimport './b'\n"},
            {"rel": "src/b.ts", "ext": ".ts", "text": "export const b = 1\n"},
            {"rel": "src/c.ts", "ext": ".ts", "text": "import './b'\n"},
        ]
        self.assertEqual(reverse_importers(files)["src/b.ts"], ["src/a.ts", "src/c.ts"])


class PipelineTests(unittest.TestCase):
    def make_repo(self, tmp):
        repo = Path(tmp) / "repo"
        (repo / "src" / "api").mkdir(parents=True)
        (repo / "src" / "db").mkdir(parents=True)
        (repo / "package.json").write_text(
            '{"name":"r","dependencies":{"express":"^4"},'
            '"devDependencies":{"vitest":"^1"}}')
        (repo / "src" / "api" / "routes.ts").write_text(
            "import { run } from '../db/store'\n"
            "const app = require('express')()\n"
            "app.get('/x', (req, res) => { run(req.query.q) })\n")
        (repo / "src" / "db" / "store.ts").write_text(
            "export function run(q: string) {\n  return eval(q)\n}\n")
        return repo

    def test_cross_package_defect_pays_the_boundary_term(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            out = Path(tmp) / "out"
            gate = run(["gate", repo, "--min-loc", "1", "--out", out])
            self.assertEqual(gate.returncode, 0, gate.stdout + gate.stderr)
            result = run(["detect", repo, "--out", out])
            self.assertEqual(result.returncode, 0, result.stderr)
            findings = [json.loads(line) for line in
                        (out / "defects.jsonl").read_text().splitlines() if line.strip()]
            eval_finding = next(f for f in findings if f["rule"] == "js-eval")
            self.assertEqual(eval_finding["effort"], 2)  # 1 + boundary, tests present
            self.assertTrue(any("boundary" in d for d in eval_finding["effort_drivers"]))

    def test_rank_rejects_model_supplied_effort(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            run(["gate", FIXTURES / "express-app", "--min-loc", "1", "--out", out])
            run(["detect", FIXTURES / "express-app", "--out", out])
            (out / "failure-modes.jsonl").write_text(
                '{"id":"f_1","class":"failure-mode","taxonomy":"missing-idempotency",'
                '"file":"src/routes.ts","line":9,"evidence":"await chargeCard(event.amount)",'
                '"counter_evidence":"Maybe fine.","detector":"llm","confidence":"med",'
                '"reach":5,"blast":5,"silence":3,"effort":2}\n')
            result = run(["rank", FIXTURES / "express-app", "--out", out])
            self.assertEqual(result.returncode, 1)
            self.assertIn("derived from the rubric", result.stderr)
            self.assertFalse((out / "ranked.json").exists())

    def test_trust_model_effort_flag_accepts_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            run(["gate", FIXTURES / "express-app", "--min-loc", "1", "--out", out])
            run(["detect", FIXTURES / "express-app", "--out", out])
            (out / "failure-modes.jsonl").write_text(
                '{"id":"f_1","class":"failure-mode","taxonomy":"missing-idempotency",'
                '"file":"src/routes.ts","line":9,"evidence":"await chargeCard(event.amount)",'
                '"counter_evidence":"Maybe fine.","detector":"llm","confidence":"med",'
                '"reach":5,"blast":5,"silence":3,"effort":4}\n')
            result = run(["rank", FIXTURES / "express-app", "--out", out, "--trust-model-effort"])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            ranked = json.loads((out / "ranked.json").read_text())
            record = next(f for f in ranked["findings"] if f["id"] == "f_1")
            self.assertEqual(record["effort"], 4)

    def test_validate_rejects_initiative_effort(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "failure-modes.jsonl"
            path.write_text(
                '{"id":"f_1","class":"failure-mode","taxonomy":"missing-idempotency",'
                '"file":"src/routes.ts","line":9,"evidence":"await chargeCard(event.amount)",'
                '"counter_evidence":"Maybe fine.","detector":"llm","confidence":"med",'
                '"reach":5,"blast":5,"silence":3,"effort":2}\n')
            result = run(["validate", path, "--repo", FIXTURES / "express-app"])
            self.assertEqual(result.returncode, 1)
            self.assertIn("derived by rank", result.stdout)


if __name__ == "__main__":
    unittest.main()
