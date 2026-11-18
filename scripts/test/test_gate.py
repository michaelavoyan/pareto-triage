import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
CLI = HERE.parent / "pareto-triage.py"
FIXTURES = HERE.parent.parent / "fixtures"

sys.path.insert(0, str(HERE.parent))
from lib.entry import filter_entrypoints_by_language  # noqa: E402


def run(args):
    return subprocess.run(
        [sys.executable, str(CLI)] + [str(a) for a in args],
        capture_output=True,
        text=True,
    )


class GateTests(unittest.TestCase):
    def test_refuses_repo_without_supported_code_or_entrypoints(self):
        with tempfile.TemporaryDirectory() as out:
            result = run(["gate", FIXTURES / "tiny", "--out", out])
            scope = json.loads((Path(out) / "scope.json").read_text())
            self.assertEqual(result.returncode, 1)
            self.assertFalse(scope["gate"]["ok"])
            reasons = " / ".join(scope["gate"]["reasons"])
            self.assertIn("supports", reasons)
            self.assertIn("entrypoints", reasons)
            self.assertEqual(scope["entrypoints"], [])

    def test_passes_small_express_app_with_overridden_threshold(self):
        with tempfile.TemporaryDirectory() as out:
            result = run(["gate", FIXTURES / "express-app", "--min-loc", "10", "--out", out])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            scope = json.loads((Path(out) / "scope.json").read_text())
            self.assertTrue(scope["gate"]["ok"])
            self.assertIn("express", [f["name"] for f in scope["frameworks"]])
            self.assertEqual(scope["tests"]["runner"], "vitest")
            self.assertGreaterEqual(scope["entrypoint_kinds"]["http"], 2)
            details = [e["detail"] for e in scope["entrypoints"] if e["kind"] == "http"]
            self.assertTrue(any("/webhooks/stripe" in d for d in details), details)
            self.assertTrue(any("/health" in d for d in details), details)

    def test_output_is_deterministic_apart_from_timestamp(self):
        outputs = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as out:
                run(["gate", FIXTURES / "express-app", "--min-loc", "10", "--out", out])
                scope = json.loads((Path(out) / "scope.json").read_text())
                scope["generated_at"] = None
                outputs.append(json.dumps(scope, sort_keys=True))
        self.assertEqual(outputs[0], outputs[1])

    def test_refusal_does_not_claim_a_report_exists(self):
        with tempfile.TemporaryDirectory() as out:
            result = run(["gate", FIXTURES / "tiny", "--out", out])
            self.assertIn("REFUSED", result.stdout)
            self.assertIn("Do not improvise a report", result.stdout)


class UnsupportedLanguageTests(unittest.TestCase):
    def test_scope_counts_files_per_unsupported_language(self):
        with tempfile.TemporaryDirectory() as out:
            result = run(["gate", FIXTURES / "mixed-lang", "--min-loc", "1", "--out", out])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            scope = json.loads((Path(out) / "scope.json").read_text())
            counts = {entry["lang"]: entry["files"] for entry in scope["size"]["unsupported"]}
            self.assertEqual(counts, {"cpp": 2, "c": 1})
            self.assertEqual(scope["languages"]["unsupported"], ["cpp", "c"])
            self.assertIn("cpp (2 files", result.stdout)

    def test_a_header_is_not_counted_as_a_c_file(self):
        with tempfile.TemporaryDirectory() as out:
            run(["gate", FIXTURES / "mixed-lang", "--min-loc", "1", "--out", out])
            scope = json.loads((Path(out) / "scope.json").read_text())
        c_entry = next(e for e in scope["size"]["unsupported"] if e["lang"] == "c")
        text = (FIXTURES / "mixed-lang" / "native" / "three.c").read_text()
        self.assertEqual(c_entry["loc"], sum(1 for line in text.split("\n") if line.strip()))
        self.assertTrue((FIXTURES / "mixed-lang" / "native" / "four.h").exists())


class PythonGateUnchangedTests(unittest.TestCase):
    """Phase 0/1 add languages. What Python repos print must not move."""

    def test_python_app_gate_output_is_byte_identical(self):
        golden = (HERE / "golden" / "python-app-gate.txt").read_text()
        with tempfile.TemporaryDirectory() as out:
            result = run(["gate", FIXTURES / "python-app", "--min-loc", "10", "--out", out])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            repo = str((FIXTURES / "python-app").resolve())
            text = result.stdout.replace(repo, "<root>")
            text = text.replace(str(Path(out).resolve()), "<out>")
        self.assertEqual(text, golden)


class EntrypointLanguageGateTests(unittest.TestCase):
    """A helper language must not supply the seeds for a repo it does not carry."""

    def test_gate_ignores_entrypoints_below_the_language_floor_and_names_the_language(self):
        with tempfile.TemporaryDirectory() as out:
            result = run(["gate", FIXTURES / "swift-python", "--min-loc", "1", "--out", out])
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            scope = json.loads((Path(out) / "scope.json").read_text())
        self.assertFalse(scope["gate"]["ok"])
        self.assertEqual(scope["entrypoints"], [])
        self.assertEqual([entry["lang"] for entry in scope["entrypoints_ignored"]], ["python"])
        self.assertEqual(scope["entrypoints_ignored"][0]["entrypoints"], 2)
        self.assertLess(scope["entrypoints_ignored"][0]["share"], 0.05)
        self.assertEqual(scope["gate"]["entrypoint_language_floor"], 0.05)
        self.assertIn("below the 5% floor", " / ".join(scope["gate"]["reasons"]))
        warning = next(w for w in scope["warnings"] if "ignored" in w)
        self.assertIn("python", warning)
        self.assertIn("5%", warning)

    def test_gate_keeps_entrypoints_when_their_language_carries_the_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            out = Path(tmp) / "out"
            (repo / "app").mkdir(parents=True)
            (repo / "app" / "main.py").write_text(
                "#!/usr/bin/env python3\nimport sys\n\n\n"
                "def main():\n    print(sys.argv)\n\n\n"
                "if __name__ == '__main__':\n    main()\n", encoding="utf-8")
            (repo / "Store.swift").write_text(
                "import Foundation\n\nstruct Store {\n"
                + "".join("    func value%d() -> Int { %d }\n" % (i, i) for i in range(12))
                + "}\n", encoding="utf-8")
            result = run(["gate", repo, "--min-loc", "1", "--out", out])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            scope = json.loads((out / "scope.json").read_text())
        self.assertTrue(scope["gate"]["ok"])
        self.assertEqual(scope["entrypoints_ignored"], [])
        self.assertTrue(scope["entrypoints"])

    def test_the_floor_is_five_percent_of_supported_lines(self):
        entries = [{"kind": "cli", "file": "tools/run.py", "line": 1, "detail": "main"}]
        at_floor = [{"lang": "swift", "files": 1, "loc": 95},
                    {"lang": "python", "files": 1, "loc": 5}]
        below = [{"lang": "swift", "files": 1, "loc": 96},
                 {"lang": "python", "files": 1, "loc": 4}]
        self.assertEqual(filter_entrypoints_by_language(entries, at_floor), (entries, []))
        kept, ignored = filter_entrypoints_by_language(entries, below)
        self.assertEqual(kept, [])
        self.assertEqual(ignored[0]["lang"], "python")

    def test_a_manifest_entrypoint_is_not_judged_by_line_share(self):
        entries = [{"kind": "cli", "file": "package.json", "line": 1, "detail": "bin"}]
        supported = [{"lang": "swift", "files": 1, "loc": 1000}]
        kept, ignored = filter_entrypoints_by_language(entries, supported)
        self.assertEqual(kept, entries)
        self.assertEqual(ignored, [])


class ValidateTests(unittest.TestCase):
    def test_accepts_well_formed_finding(self):
        result = run([
            "validate",
            FIXTURES / "express-app" / "findings.good.jsonl",
            "--repo", FIXTURES / "express-app",
        ])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("1 valid", result.stdout)

    def test_rejects_hallucinated_evidence_and_missing_counter_evidence(self):
        result = run([
            "validate",
            FIXTURES / "express-app" / "findings.bad.jsonl",
            "--repo", FIXTURES / "express-app",
        ])
        self.assertEqual(result.returncode, 1)
        self.assertIn("hallucination guard", result.stdout)
        self.assertIn("counter_evidence", result.stdout)
        self.assertIn("taxonomy must be one of", result.stdout)

    def test_empty_input_is_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "empty.jsonl"
            empty.write_text("")
            result = run(["validate", empty, "--repo", FIXTURES / "express-app"])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("empty input is a valid result", result.stdout)


class PhaseGateTests(unittest.TestCase):
    def test_unimplemented_phase_writes_nothing(self):
        with tempfile.TemporaryDirectory() as out:
            result = run(["verify", FIXTURES / "express-app", "--out", out])
            self.assertEqual(result.returncode, 2)
            self.assertIn("run: pareto-triage gate", result.stderr)
            self.assertEqual(list(Path(out).iterdir()), [])

    def test_each_phase_requires_its_input_artifact(self):
        for command, hint in (("detect", "run: pareto-triage gate"), ("rank", "run: pareto-triage gate"),
                              ("report", "run: pareto-triage rank")):
            with tempfile.TemporaryDirectory() as out:
                result = run([command, FIXTURES / "express-app", "--out", out])
                self.assertEqual(result.returncode, 2, command)
                self.assertIn(hint, result.stderr, command)
                self.assertEqual(list(Path(out).iterdir()), [], command)


if __name__ == "__main__":
    unittest.main()
