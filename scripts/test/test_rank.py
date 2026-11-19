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
from lib.score import annotate, cluster_findings, shape, quadrant  # noqa: E402


def run(args):
    return subprocess.run([sys.executable, str(CLI)] + [str(a) for a in args],
                          capture_output=True, text=True)


def finding(**overrides):
    base = {
        "id": "d_0001",
        "class": "defect",
        "rule": "py-eval",
        "taxonomy": "code-injection",
        "file": "a.py",
        "line": 1,
        "evidence": "eval(x)",
        "blast": 5,
        "silence": 2,
        "effort": 1,
    }
    base.update(overrides)
    return base


class ScoringTests(unittest.TestCase):
    def test_impact_is_blast_times_silence_over_three(self):
        items = annotate([finding(blast=5, silence=3, effort=1)])
        self.assertAlmostEqual(items[0]["impact"], 5.0)
        self.assertAlmostEqual(items[0]["priority"], 5.0)

    def test_cluster_uses_noisy_or_and_one_fix_effort(self):
        items = annotate([
            finding(id="d_1", line=1, blast=5, silence=2, effort=1),
            finding(id="d_2", line=2, blast=5, silence=2, effort=1),
        ])
        clusters = cluster_findings(items)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["n_sites"], 2)
        self.assertAlmostEqual(clusters[0]["impact"], round(5 * (1 - (1 - 3.3333 / 5) ** 2), 4))
        self.assertEqual(clusters[0]["effort"], 1.4)

    def test_shortcut_verdict_when_impact_concentrates(self):
        clusters = [
            {"key": "a", "impact": 9.0, "effort": 1.0},
            {"key": "b", "impact": 0.5, "effort": 1.0},
            {"key": "c", "impact": 0.4, "effort": 1.0},
            {"key": "d", "impact": 0.3, "effort": 1.0},
            {"key": "e", "impact": 0.3, "effort": 1.0},
        ]
        info = shape(clusters)
        self.assertEqual(info["verdict"], "shortcut")
        self.assertGreaterEqual(info["c20"], 0.6)

    def test_flat_verdict_when_impact_is_spread(self):
        clusters = [{"key": str(i), "impact": 1.0, "effort": 2.0} for i in range(10)]
        info = shape(clusters)
        self.assertEqual(info["verdict"], "flat")
        self.assertLess(info["c20"], 0.3)

    def test_one_or_two_clusters_cannot_support_a_shape_verdict(self):
        for count in (1, 2):
            clusters = [{"key": str(i), "impact": 5.0 - i, "effort": 1.0}
                        for i in range(count)]
            info = shape(clusters)
            self.assertEqual(info["verdict"], "insufficient", count)
            self.assertEqual(info["n_clusters"], count)
            self.assertGreaterEqual(info["min_clusters"], 3)
            self.assertIsInstance(info["c20"], float)

    def test_three_clusters_are_enough_for_a_real_verdict(self):
        clusters = [{"key": "big", "impact": 8.0, "effort": 1.0},
                    {"key": "a", "impact": 1.0, "effort": 1.0},
                    {"key": "b", "impact": 1.0, "effort": 1.0}]
        info = shape(clusters)
        self.assertNotEqual(info["verdict"], "insufficient")
        self.assertEqual(info["verdict"], "shortcut")

    def test_quadrant_splits_on_medians(self):
        items = [
            {"id": "a", "impact": 5.0, "effort": 1},
            {"id": "b", "impact": 4.0, "effort": 5},
            {"id": "c", "impact": 1.0, "effort": 1},
            {"id": "d", "impact": 1.0, "effort": 5},
        ]
        result = quadrant(items)
        self.assertEqual(result["counts"], {"quick_wins": 1, "batch_2": 1, "free": 1, "skip": 1})


class RankPipelineTests(unittest.TestCase):
    def test_rank_writes_a_ranked_artifact_and_is_stable(self):
        outputs = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp)
                run(["gate", FIXTURES / "python-app", "--min-loc", "5", "--out", out])
                run(["detect", FIXTURES / "python-app", "--out", out])
                result = run(["rank", FIXTURES / "python-app", "--out", out])
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                ranked = json.loads((out / "ranked.json").read_text())
                ranked.pop("generated_at", None)
                outputs.append(json.dumps(ranked, sort_keys=True))

        self.assertEqual(outputs[0], outputs[1])
        ranked = json.loads(outputs[0])
        self.assertEqual(ranked["coverage"]["defects"], 3)
        self.assertIn(ranked["shape"]["verdict"], {"shortcut", "moderate", "flat", "concentrated-expensive"})
        self.assertTrue(ranked["could_not_determine"])
        self.assertEqual(len(ranked["findings"]), 3)

    def test_rank_refuses_without_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            run(["gate", FIXTURES / "python-app", "--min-loc", "5", "--out", out])
            result = run(["rank", FIXTURES / "python-app", "--out", out])
            self.assertEqual(result.returncode, 2)
            self.assertIn("run: pareto-triage detect", result.stderr)

    def test_ignored_language_line_counts_files_not_scanned_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            run(["gate", FIXTURES / "mixed-lang", "--min-loc", "1", "--out", out])
            run(["detect", FIXTURES / "mixed-lang", "--out", out])
            result = run(["rank", FIXTURES / "mixed-lang", "--out", out])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            ranked = json.loads((out / "ranked.json").read_text())
            ignored = next(line for line in ranked["could_not_determine"]
                           if line.startswith("ignored languages:"))
            self.assertIn("cpp (2 files)", ignored)
            self.assertIn("c (1 file)", ignored)
            self.assertNotIn("6 files", ignored)

    def test_rule_coverage_is_written_to_the_ranking(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            run(["gate", FIXTURES / "ios-app", "--min-loc", "1", "--out", out])
            run(["detect", FIXTURES / "ios-app", "--out", out])
            result = run(["rank", FIXTURES / "ios-app", "--out", out])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            ranked = json.loads((out / "ranked.json").read_text())

        swift = next(row for row in ranked["rule_coverage"]["by_language"]
                     if row["lang"] == "swift")
        self.assertEqual(swift["files_with_rules"], 0)
        line = next(item for item in ranked["could_not_determine"]
                    if item.startswith("no rules were applied to"))
        self.assertIn("files of Swift", line)
        self.assertIn("says nothing about defects in them", line)

    def test_a_covered_language_gets_no_unruled_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            run(["gate", FIXTURES / "python-app", "--min-loc", "5", "--out", out])
            run(["detect", FIXTURES / "python-app", "--out", out])
            result = run(["rank", FIXTURES / "python-app", "--out", out])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            ranked = json.loads((out / "ranked.json").read_text())

        self.assertFalse([item for item in ranked["could_not_determine"]
                          if item.startswith("no rules were applied to")])
        python = ranked["rule_coverage"]["by_language"][0]
        self.assertEqual(python["lang"], "python")
        self.assertEqual(python["files_with_rules"], python["files"])

    def test_report_renders_offline_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            run(["gate", FIXTURES / "python-app", "--min-loc", "5", "--out", out])
            run(["detect", FIXTURES / "python-app", "--out", out])
            run(["rank", FIXTURES / "python-app", "--out", out])
            result = run(["report", FIXTURES / "python-app", "--out", out])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            html = (out / "report.html").read_text()
            self.assertIn("<!doctype html>", html)
            self.assertNotIn("<script", html)
            self.assertNotIn("https://", html)
            for section in ("Shape", "Curve", "Quadrant", "Top five", "Verification",
                            "Batch plan", "All findings", "Could not determine"):
                self.assertIn(section, html)
            positions = [html.index("<h2>%s" % section) for section in
                         ("Shape", "Curve", "Quadrant", "Top five", "Verification",
                          "Batch plan", "All findings", "Could not determine")]
            self.assertEqual(positions, sorted(positions))
            self.assertIn("Not run.", html)


class DedupeTests(unittest.TestCase):
    def test_duplicate_record_keeps_the_more_confident_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            run(["gate", FIXTURES / "express-app", "--min-loc", "1", "--out", out])
            run(["detect", FIXTURES / "express-app", "--out", out])
            base = {
                "class": "failure-mode", "taxonomy": "missing-idempotency",
                "file": "src/billing.ts", "line": 3,
                "evidence": "body: String(amount)", "counter_evidence": "Maybe fine.",
                "detector": "llm", "reach": 2, "blast": 5, "silence": 3,
            }
            records = [dict(base, id="f_low", confidence="low"),
                       dict(base, id="f_med", confidence="med")]
            (out / "failure-modes.jsonl").write_text(
                "".join(json.dumps(r) + "\n" for r in records))

            result = run(["rank", FIXTURES / "express-app", "--out", out])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("dedupe", result.stdout)
            ranked = json.loads((out / "ranked.json").read_text())
            ids = {f["id"] for f in ranked["findings"]}
            self.assertIn("f_med", ids)
            self.assertNotIn("f_low", ids)


class StalenessTests(unittest.TestCase):
    def build(self, out):
        run(["gate", FIXTURES / "python-app", "--min-loc", "5", "--out", out])
        run(["detect", FIXTURES / "python-app", "--out", out])
        run(["rank", FIXTURES / "python-app", "--out", out])

    def test_rewritten_findings_make_the_report_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.build(out)
            defects = out / "defects.jsonl"
            findings = [json.loads(line) for line in defects.read_text().splitlines() if line.strip()]
            findings[0]["blast"] = 2
            defects.write_text("".join(json.dumps(f, sort_keys=True) + "\n" for f in findings))

            result = run(["report", FIXTURES / "python-app", "--out", out])
            self.assertEqual(result.returncode, 1)
            self.assertIn("stale", result.stderr)
            self.assertFalse((out / "report.html").exists())

    def test_allow_stale_publishes_with_a_banner(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.build(out)
            (out / "defects.jsonl").write_text("")
            result = run(["report", FIXTURES / "python-app", "--out", out, "--allow-stale"])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            html = (out / "report.html").read_text()
            self.assertIn("STALE", html)

    def test_verification_from_a_different_ranking_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.build(out)
            (out / "verify.json").write_text(json.dumps({
                "input_hash": "not-the-current-one",
                "counts": {"reproduced": 1},
                "clusters": [{"cluster": "x", "status": "reproduced"}],
            }))
            result = run(["report", FIXTURES / "python-app", "--out", out])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("different ranking", result.stderr)
            html = (out / "report.html").read_text()
            self.assertIn("Not run.", html)
            self.assertNotIn("reproduced by an executable probe", html)

    def test_rank_records_input_and_source_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.build(out)
            ranked = json.loads((out / "ranked.json").read_text())
            self.assertTrue(ranked["sources_hash"])
            self.assertTrue(ranked["inputs_hash"]["defects"])
            self.assertIn("generated_at", ranked)


if __name__ == "__main__":
    unittest.main()
