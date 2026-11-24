"""The sampling filter: enough body to read, and something that can fail.

Phase 2 was judging three-line accessors and one-liners, which cannot contain a
failure mode. These tests pin the filter to the sampling step and prove the
population (`--all`) still holds every candidate.
"""

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
from lib.context import (body_size, extract_sites, failure_surface, is_judgeable,
                         select_sites_with_remainder)  # noqa: E402


def run(args):
    return subprocess.run([sys.executable, str(CLI)] + [str(a) for a in args],
                          capture_output=True, text=True)


def site(file, function, source, reach=4):
    lines = source.split("\n")
    return {"file": file, "function": function, "lines": [1, len(lines)],
            "reach": reach, "source": source, "lang": "py", "surrounding": "",
            "truncated": False, "site_id": function}


def py_file(rel, text):
    return {"rel": rel, "ext": ".py", "text": text}


ROUTE = ("def route():\n"
         "    try:\n"
         "        helper()\n"
         "    except ValueError:\n"
         "        pass\n")


class JudgeableTests(unittest.TestCase):
    def test_three_non_blank_lines_are_not_judgeable(self):
        body = "def f():\n    try:\n        return 1"
        self.assertEqual(body_size(site("a.py", "f", body)), 3)
        self.assertFalse(is_judgeable(site("a.py", "f", body)))

    def test_blank_lines_do_not_count_toward_the_minimum(self):
        body = "def f():\n\n    try:\n\n        return 1\n"
        self.assertEqual(body_size(site("a.py", "f", body)), 3)
        self.assertFalse(is_judgeable(site("a.py", "f", body)))

    def test_a_long_body_without_a_failure_surface_is_not_judgeable(self):
        body = ("def f():\n"
                "    a = 1\n"
                "    b = 2\n"
                "    c = 3\n"
                "    return a + b + c\n")
        self.assertEqual(failure_surface(site("a.py", "f", body)), [])
        self.assertFalse(is_judgeable(site("a.py", "f", body)))

    def test_each_failure_surface_makes_a_four_line_body_judgeable(self):
        bodies = {
            "try/catch": "def f():\n    try:\n        go()\n    except E:\n        pass\n",
            "async": "suspend fun f() {\n    withContext(io) {\n        go()\n    }\n}\n",
            "network": "fun f() {\n    val call = client.newCall(req)\n    call.execute()\n}\n",
            "db write": "fun f() {\n    db.delete(table)\n    db.update(row)\n}\n",
            "loop": "def f():\n    for row in rows:\n        go(row)\n    return 0\n",
        }
        for label, body in bodies.items():
            found = failure_surface(site("a.py", "f", body))
            self.assertIn(label, found, (label, body))
            self.assertTrue(is_judgeable(site("a.py", "f", body)), label)

    def test_await_alone_is_a_failure_surface(self):
        body = "async def f():\n    value = await load()\n    return value\n"
        self.assertIn("async", failure_surface(site("a.py", "f", body)))


class JudgeableSelectionTests(unittest.TestCase):
    def setUp(self):
        self.good = [site("a.py", "good%d" % i, ROUTE) for i in range(3)]
        self.short = [site("b.py", "short%d" % i, "def f():\n    return 1\n")
                      for i in range(3)]

    def test_only_judgeable_sites_fill_the_cap(self):
        selected, population, plan = select_sites_with_remainder(
            self.good + self.short, {}, limit=2, per_file=10, order="ranked",
            judgeable=True)
        self.assertEqual([s["function"] for s in selected], ["good0", "good1"])
        self.assertEqual(plan["judgeable"], 3)
        self.assertEqual(plan["filtered"], 3)
        self.assertEqual(plan["fallback"], 0)
        self.assertEqual(len(population), 6)
        self.assertEqual([s["function"] for s in population[:2]],
                         ["good0", "good1"])

    def test_fewer_judgeable_sites_than_the_limit_uses_a_ranked_fallback(self):
        selected, population, plan = select_sites_with_remainder(
            self.short + self.good[:1], {}, limit=4, per_file=10, order="ranked",
            judgeable=True)
        self.assertEqual(plan["judgeable"], 1)
        self.assertEqual(plan["filtered"], 3)
        self.assertEqual(plan["fallback"], 3)
        self.assertEqual([s["function"] for s in selected],
                         ["good0", "short0", "short1", "short2"])

    def test_without_the_filter_the_population_is_untouched(self):
        selected, _, plan = select_sites_with_remainder(
            self.good + self.short, {}, limit=2, per_file=10, order="ranked")
        self.assertEqual((plan["filtered"], plan["fallback"]), (0, 0))

    def test_all_sites_still_returns_the_whole_population(self):
        files = [py_file("app.py", ROUTE + "\ndef helper():\n    return 1\n")]
        sites, summary = extract_sites(files, lambda rel: 5, max_sites=1, all_sites=True)
        self.assertEqual([s["function"] for s in sites], ["route", "helper"])
        self.assertEqual(summary["emitted"], 1)
        self.assertEqual(summary["judgeable_candidates"], 1)
        self.assertEqual(summary["judgeable_filtered"], 1)


class JudgeableCliTests(unittest.TestCase):
    def _repo(self, root, judgeable=True):
        root.mkdir(parents=True)
        body = ROUTE if judgeable else "def handler():\n    return 1\n"
        (root / "app.py").write_text(
            body + "\n\ndef helper():\n    return 2\n\n"
            "\nif __name__ == '__main__':\n    print('ok')\n", encoding="utf-8")
        return root

    def _gate(self, repo, out):
        result = run(["gate", repo, "--min-loc", "1", "--out", out])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_context_keeps_only_judgeable_sites_and_records_the_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(Path(tmp) / "repo")
            out = Path(tmp) / "out"
            self._gate(repo, out)
            result = run(["context", repo, "--out", out, "--limit", "1"])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            kept = [json.loads(line) for line in
                    (out / "context.jsonl").read_text().splitlines() if line]
            self.assertEqual([record["function"] for record in kept], ["route"])
            self.assertIn("judgeable", result.stdout)
            self.assertIn("1 filtered from the sample", result.stdout)

            payload = json.loads((out / "sample.json").read_text())
            self.assertEqual(payload["judgeable"], 1)
            self.assertEqual(payload["judgeable_detail"],
                             {"candidates": 1, "filtered": 1, "fallback": 0})

            run(["context", repo, "--out", out, "--all", "--sample-order", "ranked"])
            population = [json.loads(line) for line in
                          (out / "candidates.jsonl").read_text().splitlines() if line]
            self.assertEqual([record["function"] for record in population],
                             ["route", "helper"])
            detail = json.loads((out / "sample.json").read_text())["judgeable_detail"]
            self.assertEqual(detail, {"candidates": 1, "filtered": 1, "fallback": 1})

    def test_a_repo_with_fewer_judgeable_sites_than_the_limit_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(Path(tmp) / "repo", judgeable=False)
            out = Path(tmp) / "out"
            self._gate(repo, out)
            result = run(["context", repo, "--out", out, "--limit", "5"])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            kept = [json.loads(line) for line in
                    (out / "context.jsonl").read_text().splitlines() if line]
            self.assertEqual([record["function"] for record in kept],
                             ["handler", "helper"])
            self.assertIn("only 0 judgeable site(s) for a limit of 5", result.stdout)
            self.assertIn("ranked fallback", result.stdout)
            payload = json.loads((out / "sample.json").read_text())
            self.assertEqual(payload["judgeable"], 0)
            self.assertEqual(payload["judgeable_detail"],
                             {"candidates": 0, "filtered": 2, "fallback": 2})


if __name__ == "__main__":
    unittest.main()
