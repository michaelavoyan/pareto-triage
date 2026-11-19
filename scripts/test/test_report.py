import json
import re
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
from lib.render import render  # noqa: E402
from lib.score import curve_markers  # noqa: E402


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


class MarkerTests(unittest.TestCase):
    def test_markers_accumulate_until_the_budget_is_reached(self):
        clusters = [
            {"key": "a", "impact": 8.0, "effort": 3.0, "priority": 2.7},
            {"key": "b", "impact": 2.0, "effort": 5.0, "priority": 0.4},
        ]
        markers = curve_markers(clusters, (5, 15, 30))
        self.assertTrue(markers[0]["reached"])
        self.assertEqual(markers[0]["cum_effort"], 8.0)
        self.assertEqual(markers[0]["cum_impact_share"], 1.0)
        self.assertFalse(markers[1]["reached"])

    def test_unreachable_budgets_are_flagged(self):
        markers = curve_markers([{"key": "a", "impact": 1.0, "effort": 1.0, "priority": 1.0}])
        self.assertEqual([m["reached"] for m in markers], [False, False, False])

    def test_rank_records_markers_and_budget_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            pipeline(FIXTURES / "express-app", out)
            ranked = json.loads((out / "ranked.json").read_text())
            self.assertEqual([m["label"] for m in ranked["curve_markers"]], ["S", "M", "L"])

            result = run(["rank", FIXTURES / "express-app", "--out", out, "--budget", "1,2,3"])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            ranked = json.loads((out / "ranked.json").read_text())
            self.assertEqual([m["budget"] for m in ranked["curve_markers"]], [1, 2, 3])

    def test_bad_budget_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            pipeline(FIXTURES / "express-app", out)
            result = run(["rank", FIXTURES / "express-app", "--out", out, "--budget", "1,2"])
            self.assertEqual(result.returncode, 2)
            self.assertIn("--budget", result.stderr)


class ReportSurfaceTests(unittest.TestCase):
    def build(self, tmp):
        out = Path(tmp)
        pipeline(FIXTURES / "express-app", out)
        result = run(["report", FIXTURES / "express-app", "--out", out])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return out, json.loads((out / "ranked.json").read_text()), (out / "report.html").read_text()

    def test_every_finding_has_a_row_anchor(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, ranked, html = self.build(tmp)
            for finding in ranked["findings"]:
                self.assertIn('id="f-%s"' % finding["id"], html)

    def test_cluster_anchors_and_table_of_contents_resolve(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, ranked, html = self.build(tmp)
            self.assertIn('href="#c-js-eval"', html)
            self.assertIn('id="c-js-eval"', html)

    def test_cards_link_to_their_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, ranked, html = self.build(tmp)
            first_id = ranked["clusters"][0]["findings"][0]
            self.assertIn('href="#f-%s"' % first_id, html)

    def test_cards_show_effort_drivers(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, ranked, html = self.build(tmp)
            self.assertIn("effort drivers:", html)
            self.assertNotIn("effort drivers: unavailable", html)

    def test_capped_confidence_states_the_reason(self):
        ranked = {
            "repo_name": "r", "tool_version": "0.5.0",
            "generated_at": "now", "confidence_cap": "med",
            "confidence_cap_reason": "no test runner detected",
            "shape": {"verdict": "flat", "c20": 0.0, "n_clusters": 1, "top_n": 1},
            "quadrant": {"counts": {"quick_wins": 1, "batch_2": 0, "free": 0, "skip": 0,
                                    "median_impact": 1, "median_effort": 1}},
            "curve": [], "curve_markers": [], "coverage": {},
            "clusters": [{"key": "py-eval", "taxonomy": "code-injection", "class": "defect",
                          "n_sites": 1, "impact": 5.0, "effort": 1.0, "priority": 5.0,
                          "findings": ["d_1"], "message": "eval", "file": "a.py", "line": 2}],
            "findings": [{"id": "d_1", "taxonomy": "code-injection", "class": "defect",
                          "file": "a.py", "line": 2, "evidence": "eval(x)", "reach": 5,
                          "blast": 5, "silence": 3, "effort": 1, "impact": 5.0,
                          "priority": 5.0, "confidence": "med", "confidence_capped": True,
                          "confidence_reason": "no test runner detected",
                          "effort_drivers": ["1 file", "0 importers"]}],
            "blocking_security": [], "could_not_determine": ["something"], "redactions": [],
        }
        html = render(ranked, {"root": ".", "entrypoints": [], "tests": {"present": False}})
        self.assertIn("med confidence (capped: no test runner detected)", html)
        self.assertIn("effort drivers: 1 file, 0 importers", html)

    def test_long_lists_are_truncated_with_a_pointer_to_json(self):
        findings = []
        for i in range(620):
            findings.append({
                "id": "d_%04d" % i, "taxonomy": "code-injection", "class": "defect",
                "file": "a.py", "line": i + 1, "evidence": "eval(x)", "reach": 5,
                "blast": 5, "silence": 3, "effort": 1, "impact": 5.0, "priority": 5.0,
            })
        ranked = {
            "repo_name": "r", "tool_version": "0.5.0",
            "generated_at": "now", "confidence_cap": None, "confidence_cap_reason": None,
            "shape": {"verdict": "flat", "c20": 0.0, "n_clusters": 1, "top_n": 1},
            "quadrant": {"counts": {"quick_wins": 620, "batch_2": 0, "free": 0, "skip": 0}},
            "curve": [], "curve_markers": [], "coverage": {},
            "clusters": [{"key": "code-injection", "taxonomy": "code-injection",
                          "class": "defect", "n_sites": 620, "impact": 5.0, "effort": 1.0,
                          "priority": 5.0, "findings": [f["id"] for f in findings],
                          "message": "eval", "file": "a.py", "line": 1}],
            "findings": findings, "blocking_security": [],
            "could_not_determine": ["x"], "redactions": [],
        }
        html = render(ranked, {"root": ".", "entrypoints": [], "tests": {"present": False}})
        self.assertIn("Showing 500 of 620 findings", html)
        self.assertEqual(len(re.findall(r'<tr id="f-', html)), 500)


class SectionClaimTests(unittest.TestCase):
    """One assertion per required claim in report-format.md."""

    def test_every_section_carries_its_required_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            pipeline(FIXTURES / "express-app", out)
            result = run(["report", FIXTURES / "express-app", "--out", out])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            html = (out / "report.html").read_text()
            ranked = json.loads((out / "ranked.json").read_text())
            ranked = json.loads((out / "report.json").read_text())

        # 1. Shape: the measured verdict, not a promise.
        self.assertIn(ranked["shape"]["verdict"], html)
        # 2. Curve: a budget statement exists, reached or explicitly not.
        self.assertTrue("effort units" in html)
        # 3. Quadrant: four labelled cells with counts.
        for label in ("do now", "schedule", "anytime", "ignore"):
            self.assertIn(label, html)
        # 4. Top five: the evidence itself, quoted.
        top = ranked["clusters"][0]
        sample = next(f for f in ranked["findings"] if f["id"] == top["findings"][0])
        self.assertIn(sample["evidence"].split("\n")[0][:40], html)
        # 5. Verification: present in one of its two honest states.
        self.assertTrue("Not run." in html or "reproduced by an executable probe" in html)
        # 6. Batch plan: rows with counts, not percentages.
        self.assertIn("High impact, low effort", html)
        # 7. All findings: table of contents and a row anchor.
        self.assertIn('href="#c-', html)
        self.assertIn('id="f-', html)
        # 8. Could not determine: coverage and the redaction statement.
        self.assertIn("not assessed", html)


class UnprovenTests(unittest.TestCase):
    def test_unproven_entries_render_without_scores(self):
        ranked = {
            "repo_name": "r", "tool_version": "0.6.0",
            "generated_at": "now", "confidence_cap": None, "confidence_cap_reason": None,
            "shape": {"verdict": "empty", "c20": 0.0, "n_clusters": 0, "top_n": 0},
            "quadrant": {"counts": {"quick_wins": 0, "batch_2": 0, "free": 0, "skip": 0}},
            "curve": [], "curve_markers": [], "coverage": {}, "clusters": [], "findings": [],
            "blocking_security": [], "could_not_determine": ["x"], "redactions": [],
            "unproven": [{"id": "f_1", "class": "failure-mode", "taxonomy": "missing-timeout",
                          "file": "a.py", "line": 4,
                          "reason": "evidence does not appear verbatim"}],
        }
        html = render(ranked, {"root": ".", "entrypoints": [], "tests": {"present": False}})
        self.assertIn("Unproven", html)
        self.assertIn("a.py:4", html)
        self.assertIn("evidence does not appear verbatim", html)
        self.assertIn("carry no score on purpose", html)


class InsufficientShapeTests(unittest.TestCase):
    """Too few clusters: C20 is arithmetic, and the report must say so."""

    @staticmethod
    def single_cluster_report():
        ranked = {
            "repo_name": "r", "tool_version": "0.4.0",
            "generated_at": "now", "confidence_cap": None, "confidence_cap_reason": None,
            "shape": {"verdict": "insufficient", "c20": 1.0, "n_clusters": 1,
                      "min_clusters": 3, "top_n": 1},
            "quadrant": {"counts": {"quick_wins": 1, "batch_2": 0, "free": 0, "skip": 0}},
            "curve": [{"key": "py-eval", "cum_impact_share": 1.0, "cum_effort": 1.0}],
            "curve_markers": [{"label": "S", "budget": 5, "reached": False,
                               "cum_effort": 1.0, "cum_impact_share": 1.0}],
            "coverage": {},
            "pareto": {"target": 0.8, "shortcut": False, "clusters": 1, "of_clusters": 1,
                       "effort_share": 1.0, "impact_share": 1.0, "insufficient": True},
            "pareto_ladder": [{"target": t, "shortcut": False, "clusters": 1,
                               "of_clusters": 1, "effort_share": 1.0,
                               "impact_share": 1.0} for t in (0.5, 0.7, 0.8)],
            "clusters": [{"key": "py-eval", "taxonomy": "code-injection", "class": "defect",
                          "n_sites": 1, "impact": 5.0, "effort": 1.0, "priority": 5.0,
                          "findings": ["d_1"], "message": "eval", "file": "a.py", "line": 2}],
            "findings": [{"id": "d_1", "taxonomy": "code-injection", "class": "defect",
                          "file": "a.py", "line": 2, "evidence": "eval(x)", "reach": 5,
                          "blast": 5, "silence": 3, "effort": 1, "impact": 5.0,
                          "priority": 5.0, "confidence": "high",
                          "effort_drivers": ["1 file", "0 importers"]}],
            "blocking_security": [], "could_not_determine": ["x"], "redactions": [],
        }
        return render(ranked, {"root": ".", "entrypoints": [], "tests": {"present": True}})

    def test_one_cluster_report_states_the_verdict_is_not_meaningful(self):
        html = self.single_cluster_report()
        self.assertIn("Verdict not meaningful: 1 cluster is too few to judge shape", html)
        self.assertIn("C20 is 100% by arithmetic", html)
        self.assertIn("a verdict needs at least 3 clusters", html)
        self.assertIn("The effort ladder is omitted", html)
        self.assertNotIn("There is a shortcut here.", html)
        self.assertNotIn('class="verdict shortcut"', html)

    def test_two_clusters_agree_between_ladder_and_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            pipeline(FIXTURES / "express-app", out)
            ranked = json.loads((out / "ranked.json").read_text())
            self.assertEqual(ranked["shape"]["verdict"], "insufficient")
            self.assertFalse(ranked["pareto"]["shortcut"])
            self.assertTrue(all(not row["shortcut"] for row in ranked["pareto_ladder"]))

            result = run(["report", FIXTURES / "express-app", "--out", out])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("verdict    insufficient", result.stdout)
            html = (out / "report.html").read_text()

        self.assertIn("Verdict not meaningful: 2 clusters are too few to judge shape", html)
        self.assertNotIn("There is a shortcut here.", html)
        self.assertNotIn('class="verdict shortcut"', html)


if __name__ == "__main__":
    unittest.main()
