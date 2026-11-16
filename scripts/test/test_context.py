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
from lib.context import extract_sites  # noqa: E402


def run(args):
    return subprocess.run([sys.executable, str(CLI)] + [str(a) for a in args],
                          capture_output=True, text=True)


class ContextTests(unittest.TestCase):
    def test_refuses_without_scope(self):
        with tempfile.TemporaryDirectory() as out:
            result = run(["context", FIXTURES / "express-app", "--out", out])
            self.assertEqual(result.returncode, 2)
            self.assertIn("run: pareto-triage gate", result.stderr)
            self.assertEqual(list(Path(out).iterdir()), [])

    def test_writes_one_record_per_reachable_site(self):
        with tempfile.TemporaryDirectory() as out:
            run(["gate", FIXTURES / "express-app", "--min-loc", "1", "--out", out])
            result = run(["context", FIXTURES / "express-app", "--out", out])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            records = [json.loads(line) for line in
                       (Path(out) / "context.jsonl").read_text().splitlines() if line.strip()]

        self.assertTrue(records)
        ids = [r["site_id"] for r in records]
        self.assertEqual(ids, sorted(ids))
        for record in records:
            for key in ("site_id", "file", "function", "lines", "lang", "reach",
                        "call_path", "source", "surrounding"):
                self.assertIn(key, record)
            self.assertEqual(len(record["lines"]), 2)
            self.assertGreaterEqual(record["reach"], 2)
            self.assertTrue(record["call_path"])

    def test_inline_route_handlers_are_sites(self):
        with tempfile.TemporaryDirectory() as out:
            run(["gate", FIXTURES / "express-app", "--min-loc", "1", "--out", out])
            run(["context", FIXTURES / "express-app", "--out", out])
            records = [json.loads(line) for line in
                       (Path(out) / "context.jsonl").read_text().splitlines() if line.strip()]

        names = {r["function"] for r in records}
        self.assertIn("POST /webhooks/stripe", names)
        handler = next(r for r in records if r["function"] == "POST /webhooks/stripe")
        self.assertIn("chargeCard", handler["source"])

    def test_source_is_verbatim_and_quotes_from_it_pass_the_guard(self):
        with tempfile.TemporaryDirectory() as out:
            run(["gate", FIXTURES / "express-app", "--min-loc", "1", "--out", out])
            run(["context", FIXTURES / "express-app", "--out", out])
            records = [json.loads(line) for line in
                       (Path(out) / "context.jsonl").read_text().splitlines() if line.strip()]

        source = (FIXTURES / "express-app" / "src" / "routes.ts").read_text()
        handler = next(r for r in records if r["function"] == "POST /webhooks/stripe")
        self.assertIn(handler["source"], source)

    def test_unreachable_files_are_excluded(self):
        files = [
            {"rel": "src/entry.ts", "ext": ".ts", "text": "export function handler() {\n  return 1\n}\n"},
            {"rel": "src/orphan.ts", "ext": ".ts", "text": "function orphan() {\n  return 2\n}\n"},
        ]
        sites, summary = extract_sites(files, lambda rel: 5 if rel == "src/entry.ts" else 1)
        self.assertEqual([s["file"] for s in sites], ["src/entry.ts"])
        self.assertEqual(summary["unreachable_source_files"], 1)

    def test_limit_is_respected_and_reported(self):
        text = "".join("function f%d() {\n  return %d\n}\n" % (i, i) for i in range(6))
        sites, summary = extract_sites([{"rel": "a.ts", "ext": ".ts", "text": text}],
                                       lambda rel: 5, max_sites=3)
        self.assertEqual(len(sites), 3)
        self.assertTrue(summary["limit_hit"])
        self.assertEqual(summary["candidates"], 6)

    def test_unparseable_python_is_a_warning_not_a_crash(self):
        sites, summary = extract_sites([{"rel": "bad.py", "ext": ".py", "text": "def broken(:\n"}],
                                       lambda rel: 5)
        self.assertEqual(sites, [])
        self.assertEqual(len(summary["parse_errors"]), 1)

    def test_refuses_when_no_function_is_reachable(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            (repo / "src").mkdir(parents=True)
            (repo / "src" / "cli.py").write_text(
                "import sys\n\nif __name__ == '__main__':\n    print(sys.argv)\n")
            out = Path(tmp) / "out"
            gate = run(["gate", repo, "--min-loc", "1", "--out", out])
            self.assertEqual(gate.returncode, 0, gate.stdout + gate.stderr)
            result = run(["context", repo, "--out", out])
            self.assertEqual(result.returncode, 1)
            self.assertIn("no candidate sites", result.stderr)
            self.assertFalse((out / "context.jsonl").exists())

    def test_nested_functions_yield_one_site_and_remember_the_container(self):
        text = "def outer():\n    def inner():\n        return 1\n    return inner()\n"
        sites, _ = extract_sites([{"rel": "a.py", "ext": ".py", "text": text}], lambda rel: 5)
        self.assertEqual(len(sites), 1)
        self.assertEqual(sites[0]["function"], "outer.inner")
        self.assertEqual(sites[0]["enclosed_by"], ["outer"])

    def test_include_enclosing_flag_restores_both(self):
        text = "def outer():\n    def inner():\n        return 1\n    return inner()\n"
        sites, _ = extract_sites([{"rel": "a.py", "ext": ".py", "text": text}],
                                 lambda rel: 5, include_enclosing=True)
        self.assertEqual({s["function"] for s in sites}, {"outer", "outer.inner"})

    def test_js_nested_arrows_collapse(self):
        text = ("function outer() {\n"
                "  const inner = () => {\n    return 1\n  }\n"
                "  return inner()\n}\n")
        sites, _ = extract_sites([{"rel": "a.ts", "ext": ".ts", "text": text}], lambda rel: 5)
        self.assertEqual([s["function"] for s in sites], ["inner"])

    def test_output_is_deterministic(self):
        outputs = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as out:
                run(["gate", FIXTURES / "express-app", "--min-loc", "1", "--out", out])
                run(["context", FIXTURES / "express-app", "--out", out])
                outputs.append((Path(out) / "context.jsonl").read_text())
        self.assertEqual(outputs[0], outputs[1])


if __name__ == "__main__":
    unittest.main()
