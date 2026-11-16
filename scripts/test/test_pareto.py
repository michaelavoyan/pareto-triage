import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.score import pareto_ladder, pareto_point


def cluster(key, impact, effort):
    return {"key": key, "impact": impact, "effort": effort, "priority": impact / effort}


class ParetoPointTests(unittest.TestCase):
    def test_shortcut_reports_the_cheap_set(self):
        point = pareto_point([cluster("a", 8.0, 1.0), cluster("b", 1.0, 5.0),
                              cluster("c", 1.0, 5.0)])
        self.assertTrue(point["shortcut"])
        self.assertEqual(point["clusters"], 1)
        self.assertAlmostEqual(point["effort_share"], 0.091, places=2)

    def test_flat_reports_no_cheap_set(self):
        point = pareto_point([cluster(str(i), 2.0, 3.0) for i in range(10)])
        self.assertFalse(point["shortcut"])
        self.assertEqual(point["clusters"], 8)
        self.assertEqual(point["effort_share"], 0.8)

    def test_ladder_reports_every_target(self):
        rows = pareto_ladder([cluster("a", 8.0, 1.0), cluster("b", 2.0, 9.0)])
        self.assertEqual([row["target"] for row in rows], [0.5, 0.7, 0.8])
        self.assertTrue(all(row["effort_share"] is not None for row in rows))

    def test_empty_repo_does_not_divide_by_zero(self):
        point = pareto_point([])
        self.assertFalse(point["shortcut"])
        self.assertIsNone(point["effort_share"])


if __name__ == "__main__":
    unittest.main()
