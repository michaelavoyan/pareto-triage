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
from lib.sampling import densities, measure, random_sample_indexes  # noqa: E402


def run(args):
    return subprocess.run([sys.executable, str(CLI)] + [str(a) for a in args],
                          capture_output=True, text=True)


def site(index, lines=(1, 5), file=None):
    return {
        "site_id": "s_%03d" % (index + 1),
        "file": file or "src/f%03d.py" % index,
        "function": "fn_%d" % index,
        "lines": list(lines),
        "lang": "py",
        "reach": 4,
        "source": "def fn_%d():\n    return 1\n" % index,
    }


def finding(file, line, rule="py-eval"):
    return {"id": "d_%s_%d" % (rule, line), "class": "defect", "rule": rule,
            "file": file, "line": line}


def dirty(population, indexes, line=2):
    return [finding(population[index]["file"], line) for index in indexes]


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record) + "\n" for record in records),
                    encoding="utf-8")


class DeterminismTests(unittest.TestCase):
    def test_same_seed_gives_the_same_sample(self):
        population = [site(i) for i in range(200)]
        first = measure(population, [], limit=50, seed=3)
        second = measure(population, [], limit=50, seed=3)
        self.assertEqual(first["sample"]["random"], second["sample"]["random"])

    def test_different_seeds_draw_different_samples(self):
        population = [site(i) for i in range(200)]
        first = measure(population, [], limit=50, seed=3)
        second = measure(population, [], limit=50, seed=4)
        self.assertNotEqual(first["sample"]["random"], second["sample"]["random"])

    def test_sample_indexes_are_sorted_and_distinct(self):
        indexes = random_sample_indexes(100, 20, seed=9)
        self.assertEqual(indexes, sorted(set(indexes)))
        self.assertEqual(len(indexes), 20)

    def test_sample_never_exceeds_the_population(self):
        self.assertEqual(random_sample_indexes(5, 40, seed=0), [0, 1, 2, 3, 4])


class SeparationTests(unittest.TestCase):
    def test_selected_and_random_sets_are_not_the_same(self):
        population = [site(i) for i in range(50)]
        result = measure(population, dirty(population, range(10)), limit=10, seed=0)
        self.assertEqual(result["sample"]["selected"],
                         [s["site_id"] for s in population[:10]])
        self.assertNotEqual(set(result["sample"]["selected"]),
                            set(result["sample"]["random"]))
        self.assertEqual(result["file_density"]["selected"], 1.0)
        self.assertLess(result["file_density"]["random"], 1.0)

    def test_line_density_requires_a_finding_inside_the_site(self):
        sites = [site(0, lines=(10, 20), file="a.py"), site(1, lines=(1, 5), file="b.py")]
        found = [finding("a.py", 30), finding("b.py", 5)]
        result = densities(sites, found)
        self.assertEqual(result["file"], 1.0)
        self.assertEqual(result["line"], 0.5)


class VerdictTests(unittest.TestCase):
    def test_ordering_beats_random_when_selected_sites_carry_the_findings(self):
        population = [site(i) for i in range(100)]
        result = measure(population, dirty(population, range(20)), limit=20, seed=0)
        self.assertEqual(result["file_density"]["selected"], 1.0)
        self.assertGreater(result["file_density"]["ci95"][0], 0)
        self.assertEqual(result["verdict"], "ordering beats random")

    def test_ordering_does_not_win_when_both_sets_are_equally_dirty(self):
        population = [site(i) for i in range(100)]
        result = measure(population, dirty(population, range(100)), limit=20, seed=0)
        self.assertEqual(result["file_density"]["selected"], 1.0)
        self.assertEqual(result["file_density"]["random"], 1.0)
        self.assertEqual(result["verdict"], "indistinguishable")
        self.assertEqual(result["file_density"]["ratio"], 1.0)

    def test_ordering_is_worse_when_selected_sites_are_cleaner(self):
        population = [site(i) for i in range(100)]
        result = measure(population, dirty(population, range(20, 100)), limit=20, seed=0)
        self.assertEqual(result["file_density"]["selected"], 0.0)
        self.assertGreater(result["file_density"]["random"], 0.5)
        self.assertEqual(result["verdict"], "ordering is worse than random")


class EmptyFindingsTests(unittest.TestCase):
    def test_no_findings_means_zero_density_and_no_ratio(self):
        population = [site(i) for i in range(20)]
        result = measure(population, [], limit=5, seed=0)
        for metric in ("file_density", "line_density"):
            self.assertEqual(result[metric]["selected"], 0.0)
            self.assertEqual(result[metric]["random"], 0.0)
            self.assertIsNone(result[metric]["ratio"])
            self.assertEqual(result[metric]["ci95"], [0.0, 0.0])
        self.assertEqual(result["verdict"], "indistinguishable")


class ContextPopulationTests(unittest.TestCase):
    def test_all_writes_every_candidate_with_context_first(self):
        with tempfile.TemporaryDirectory() as out:
            run(["gate", FIXTURES / "express-app", "--min-loc", "1", "--out", out])
            result = run(["context", FIXTURES / "express-app", "--out", out,
                          "--limit", "1", "--all"])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            context = [json.loads(line) for line in
                       (Path(out) / "context.jsonl").read_text().splitlines() if line.strip()]
            population = [json.loads(line) for line in
                          (Path(out) / "candidates.jsonl").read_text().splitlines() if line.strip()]

        self.assertEqual(len(context), 1)
        self.assertGreater(len(population), len(context))
        self.assertEqual(population[:len(context)], context)
        self.assertEqual(set(population[0]), set(context[0]))
        self.assertEqual([r["site_id"] for r in population],
                         ["s_%03d" % i for i in range(1, len(population) + 1)])

    def test_save_candidates_writes_the_population_to_a_custom_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            target = Path(tmp) / "audit" / "population.jsonl"
            run(["gate", FIXTURES / "express-app", "--min-loc", "1", "--out", out])
            result = run(["context", FIXTURES / "express-app", "--out", out,
                          "--limit", "1", "--save-candidates", target])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(target.exists())
            self.assertGreater(len(target.read_text().splitlines()),
                               len((out / "context.jsonl").read_text().splitlines()))


class SamplingCommandTests(unittest.TestCase):
    def _out_with_population(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = Path(tmp.name) / "out"
        population = [site(i) for i in range(40)]
        write_jsonl(out / "candidates.jsonl", population)
        write_jsonl(out / "defects.jsonl", dirty(population, range(10)))
        write_jsonl(out / "failure-modes.jsonl",
                    [{"id": "fm_1", "class": "failure-mode", "file": population[30]["file"],
                      "line": 2, "taxonomy": "missing-timeout"}])
        return out

    def test_writes_both_densities_and_says_what_it_measures(self):
        out = self._out_with_population()
        result = run(["sampling", out.parent, "--out", out, "--limit", "10", "--seed", "5"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("verdict", result.stdout)

        payload = json.loads((out / "sampling.json").read_text())
        self.assertEqual(payload["seed"], 5)
        self.assertEqual(payload["n"], 10)
        self.assertEqual(payload["population"], 40)
        for key in ("file_density", "line_density"):
            for field in ("selected", "random", "ratio", "difference", "ci95"):
                self.assertIn(field, payload[key])
        self.assertIn("rule findings only", payload["measure"])
        self.assertEqual(payload["inputs"]["failure_modes_ignored"], 1)

    def test_failure_modes_are_never_counted(self):
        out = self._out_with_population()
        with_modes = run(["sampling", out.parent, "--out", out, "--limit", "10"]).returncode
        self.assertEqual(with_modes, 0)
        counted = json.loads((out / "sampling.json").read_text())["inputs"]["defects"]

        (out / "failure-modes.jsonl").unlink()
        without_modes = run(["sampling", out.parent, "--out", out, "--limit", "10"])
        self.assertEqual(without_modes.returncode, 0)
        self.assertEqual(json.loads((out / "sampling.json").read_text())["inputs"]["defects"],
                         counted)

    def test_missing_candidates_jsonl_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            out.mkdir()
            result = run(["sampling", tmp, "--out", out])
            self.assertEqual(result.returncode, 2)
            self.assertIn("candidates.jsonl", result.stderr)
            self.assertFalse((out / "sampling.json").exists())

    def test_missing_defects_jsonl_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            write_jsonl(out / "candidates.jsonl", [site(0)])
            result = run(["sampling", tmp, "--out", out])
            self.assertEqual(result.returncode, 2)
            self.assertIn("defects.jsonl", result.stderr)


if __name__ == "__main__":
    unittest.main()
