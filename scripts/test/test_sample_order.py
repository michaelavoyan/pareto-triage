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
from lib.context import select_sites  # noqa: E402
from lib.render import render  # noqa: E402

SENTENCE = "rule findings cover every file; this is a sample only for judgment"


def run(args):
    return subprocess.run([sys.executable, str(CLI)] + [str(a) for a in args],
                          capture_output=True, text=True)


def pipeline(repo, out):
    for command in (["gate", repo, "--min-loc", "1", "--out", out],
                    ["context", repo, "--out", out],
                    ["detect", repo, "--out", out],
                    ["rank", repo, "--out", out]):
        result = run(command)
        assert result.returncode == 0, result.stdout + result.stderr


def records(out):
    path = Path(out) / "context.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def kept(out):
    return [(r["file"], r["function"]) for r in records(out)]


def site(file, function, start=1, end=3, reach=4):
    return {"file": file, "function": function, "lines": [start, end],
            "reach": reach, "source": "x", "lang": "py", "surrounding": "",
            "truncated": False, "site_id": function}


class SampleOrderTests(unittest.TestCase):
    """The cap is filled by a seeded shuffle unless `ranked` is asked for."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.out = Path(self._tmp.name) / "out"
        result = run(["gate", FIXTURES / "sample-order", "--min-loc", "1", "--out", self.out])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def context(self, *extra):
        result = run(["context", FIXTURES / "sample-order", "--out", self.out,
                      "--limit", "5"] + list(extra))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_same_seed_gives_the_same_sample(self):
        self.context("--seed", "4")
        first = kept(self.out)
        self.context("--seed", "4")
        self.assertEqual(kept(self.out), first)

    def test_the_default_mode_is_random_and_seed_zero(self):
        self.context()
        default = kept(self.out)
        self.context("--sample-order", "random", "--seed", "0")
        self.assertEqual(kept(self.out), default)

    def test_different_seeds_give_different_samples(self):
        self.context("--seed", "1")
        first = kept(self.out)
        self.context("--seed", "2")
        self.assertNotEqual(kept(self.out), first)

    def test_ranked_mode_keeps_the_old_order(self):
        self.context("--sample-order", "ranked")
        self.assertEqual(kept(self.out), [("cli.py", "main"), ("cli.py", "alpha"),
                                          ("cli.py", "beta"), ("hub.py", "run"),
                                          ("hub.py", "one")])

    def test_random_mode_reaches_a_deep_file_that_ranked_never_reaches(self):
        # z_deep.py sorts last, so the ranked order spends all five slots on
        # cli.py and hub.py. The shuffle does not care where the file sorts.
        self.context("--sample-order", "ranked")
        self.assertNotIn("z_deep.py", {file for file, _ in kept(self.out)})

        self.context("--sample-order", "random", "--seed", "0")
        self.assertIn(("z_deep.py", "deep_handler"), kept(self.out))

    def test_per_file_cap_holds_under_random_order(self):
        candidates = ([site("a/Big.py", "m%d" % index, start=index, end=index + 2)
                       for index in range(60)]
                      + [site("b/Other.py", "n%d" % index, start=index, end=index + 2)
                         for index in range(40)])
        chosen = select_sites(candidates, {}, limit=400, per_file=20,
                              order="random", seed=11)
        counts = {}
        for item in chosen:
            counts[item["file"]] = counts.get(item["file"], 0) + 1
        self.assertEqual(len(chosen), 40)
        for name, count in counts.items():
            self.assertLessEqual(count, 20, name)

    def test_sample_json_records_the_method(self):
        result = self.context("--sample-order", "ranked", "--seed", "9")
        payload = json.loads((self.out / "sample.json").read_text())
        self.assertEqual(payload, {"mode": "ranked", "seed": 9,
                                   "population": 10, "kept": 5, "per_file": 3,
                                   "judgeable": {"candidates": 10, "filtered": 0,
                                                 "fallback": 0}})

        self.assertIn("sample     ranked, seed 9: kept 5 of 10 candidates, max 3 per file",
                      result.stdout)
        self.assertIn(SENTENCE, result.stdout)

        # The default run writes it too, with the default mode and seed.
        self.context()
        payload = json.loads((self.out / "sample.json").read_text())
        self.assertEqual((payload["mode"], payload["seed"]), ("random", 0))

    def test_context_jsonl_carries_no_sampling_metadata(self):
        self.context()
        for record in records(self.out):
            self.assertEqual(
                set(record), {"site_id", "file", "function", "lines", "lang", "reach",
                              "call_path", "source", "surrounding", "truncated"})

    def test_unknown_mode_and_non_numeric_seed_are_refused(self):
        bad_mode = run(["context", FIXTURES / "sample-order", "--out", self.out,
                        "--sample-order", "shuffled"])
        self.assertEqual(bad_mode.returncode, 2)
        self.assertIn("--sample-order", bad_mode.stderr)

        bad_seed = run(["context", FIXTURES / "sample-order", "--out", self.out,
                        "--seed", "later"])
        self.assertEqual(bad_seed.returncode, 2)
        self.assertIn("--seed", bad_seed.stderr)


class ReportSampleTests(unittest.TestCase):
    def test_report_states_the_sampling_method_when_sample_json_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            pipeline(FIXTURES / "express-app", out)
            self.assertTrue((out / "sample.json").exists())
            result = run(["report", FIXTURES / "express-app", "--out", out])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            html = (out / "report.html").read_text()
            published = json.loads((out / "report.json").read_text())

        self.assertIn("Candidate sites were sampled:", html)
        self.assertIn("Rule findings cover every file; this is a sample only for judgment.",
                      html)
        self.assertEqual(published["sample"]["mode"], "random")

    def test_report_without_sample_json_says_nothing_about_sampling(self):
        ranked = {"repo_name": "r", "tool_version": "0.2.1", "generated_at": "now",
                  "confidence_cap": None, "confidence_cap_reason": None,
                  "shape": {"verdict": "empty", "c20": 0.0, "n_clusters": 0, "top_n": 0},
                  "quadrant": {"counts": {"quick_wins": 0, "batch_2": 0, "free": 0, "skip": 0}},
                  "curve": [], "curve_markers": [], "coverage": {}, "clusters": [],
                  "findings": [], "blocking_security": [], "could_not_determine": ["x"],
                  "redactions": []}
        html = render(ranked, {"root": ".", "entrypoints": [], "tests": {"present": False}})
        self.assertNotIn("Candidate sites were sampled:", html)


class SamplingWarningTests(unittest.TestCase):
    def test_random_population_warns_that_the_comparison_is_random_against_random(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            pipeline(FIXTURES / "express-app", out)
            run(["context", FIXTURES / "express-app", "--out", out, "--all"])
            result = run(["sampling", FIXTURES / "express-app", "--out", out])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("compares random against random", result.stderr)

            run(["context", FIXTURES / "express-app", "--out", out, "--all",
                 "--sample-order", "ranked"])
            result = run(["sampling", FIXTURES / "express-app", "--out", out])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn("compares random against random", result.stderr)


if __name__ == "__main__":
    unittest.main()
