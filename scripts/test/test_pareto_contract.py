"""Black-box tests for the documented Pareto contract.

Written from references/rubric.md and report-format.md, not from the code:
impact = blast x silence / 3 with x0.25 at reach 1; priority = impact / effort;
c20 = impact share of the top fifth of clusters; verdict thresholds 0.6 and 0.3;
pareto point = cheapest set reaching a target share, reported as effort share,
shortcut only when 80% costs at most half the effort.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.score import annotate, cluster_findings, pareto_ladder, pareto_point, shape


def cluster(key, impact, effort):
    return {"key": key, "impact": impact, "effort": effort,
            "priority": impact / effort, "taxonomy": key, "class": "defect",
            "n_sites": 1, "findings": [key], "file": "a.py", "line": 1}


def site(rule, blast, silence, effort=1, reach=5):
    return {"id": "d_" + rule, "rule": rule, "class": "defect", "taxonomy": rule,
            "file": "a.py", "line": 1, "evidence": "x", "blast": blast,
            "silence": silence, "effort": effort, "reach": reach}


class ImpactTests(unittest.TestCase):
    def test_impact_is_blast_times_silence_over_three(self):
        self.assertAlmostEqual(annotate([site("r", 5, 3)])[0]["impact"], 5.0)
        self.assertAlmostEqual(annotate([site("r", 2, 3)])[0]["impact"], 2.0)

    def test_dead_code_impact_is_quartered(self):
        live = annotate([site("a", 4, 3)])[0]["impact"]
        dead = annotate([site("b", 4, 3, reach=1)])[0]["impact"]
        self.assertAlmostEqual(dead, live / 4)

    def test_priority_divides_impact_by_effort(self):
        finding = annotate([site("r", 5, 3, effort=5)])[0]
        self.assertAlmostEqual(finding["priority"], 1.0)


class ConcentrationTests(unittest.TestCase):
    def test_perfect_shortcut_is_detected(self):
        clusters = [cluster("big", 8.0, 1.0), cluster("a", 1.0, 4.0), cluster("b", 1.0, 4.0)]
        self.assertGreaterEqual(shape(clusters)["c20"], 0.6)
        self.assertEqual(shape(clusters)["verdict"], "shortcut")

    def test_flat_distribution_says_flat(self):
        clusters = [cluster(str(i), 2.0, 3.0) for i in range(10)]
        verdict = shape(clusters)
        self.assertLess(verdict["c20"], 0.3)
        self.assertEqual(verdict["verdict"], "flat")

    def test_concentrated_but_expensive_is_not_a_shortcut(self):
        clusters = [cluster("big", 8.0, 9.0), cluster("a", 1.0, 1.0), cluster("b", 1.0, 1.0)]
        verdict = shape(clusters)
        self.assertGreaterEqual(verdict["c20"], 0.6)
        self.assertEqual(verdict["verdict"], "concentrated-expensive")

    def test_mid_concentration_is_moderate(self):
        clusters = [cluster("a", 4.0, 2.0), cluster("b", 3.0, 2.0), cluster("c", 3.0, 2.0)]
        self.assertEqual(shape(clusters)["verdict"], "moderate")

    def test_no_clusters_is_empty_not_a_crash(self):
        verdict = shape([])
        self.assertEqual(verdict["verdict"], "empty")
        self.assertEqual(verdict["c20"], 0.0)


class ParetoPointTests(unittest.TestCase):
    def test_eighty_percent_for_twenty_percent_is_a_shortcut(self):
        clusters = [cluster("big", 8.0, 2.0), cluster("a", 1.0, 4.0), cluster("b", 1.0, 4.0)]
        point = pareto_point(clusters)
        self.assertTrue(point["shortcut"])
        self.assertAlmostEqual(point["effort_share"], 0.2, places=2)

    def test_failing_the_bet_still_reports_a_set(self):
        clusters = [cluster(str(i), 2.0, 3.0) for i in range(10)]
        point = pareto_point(clusters)
        self.assertFalse(point["shortcut"])
        self.assertTrue(point["effort_share"] is not None)
        self.assertAlmostEqual(point["effort_share"], 0.8, places=2)

    def test_ladder_is_monotonic_in_target(self):
        clusters = [cluster("a", 6.0, 1.0), cluster("b", 2.0, 3.0), cluster("c", 2.0, 6.0)]
        rows = pareto_ladder(clusters)
        self.assertEqual([r["target"] for r in rows], [0.5, 0.7, 0.8])
        self.assertEqual([r["clusters"] for r in rows],
                         sorted(r["clusters"] for r in rows))
        self.assertEqual([r["effort_share"] for r in rows],
                         sorted(r["effort_share"] for r in rows))

    def test_single_cluster_covers_everything_at_full_effort(self):
        point = pareto_point([cluster("only", 5.0, 3.0)])
        self.assertEqual(point["clusters"], 1)
        self.assertAlmostEqual(point["effort_share"], 1.0)


class ClusterTests(unittest.TestCase):
    def test_cluster_impact_is_above_its_largest_member_and_below_the_scale(self):
        findings = annotate([site("r", 5, 3), site("r", 5, 3)])
        clusters = cluster_findings(findings)
        self.assertEqual(len(clusters), 1)
        self.assertGreater(clusters[0]["impact"], 5.0 - 1e-9)
        self.assertLessEqual(clusters[0]["impact"], 5.0 + 1e-9)

    def test_orders_by_priority(self):
        findings = annotate([site("cheap", 5, 3, effort=1), site("dear", 5, 3, effort=5)])
        clusters = cluster_findings(findings)
        self.assertEqual([c["key"] for c in clusters], ["cheap", "dear"])


if __name__ == "__main__":
    unittest.main()
