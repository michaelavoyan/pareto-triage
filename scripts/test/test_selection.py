import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.context import is_trivial_accessor, select_sites


def site(file, function, start=1, end=10, reach=4):
    return {"file": file, "function": function, "lines": [start, end],
            "reach": reach, "source": "x", "lang": "java", "surrounding": "",
            "truncated": False, "site_id": function}


class SelectionTests(unittest.TestCase):
    """`order="ranked"` is the old reach → inbound → body size ordering."""
    def test_inbound_edges_beat_path_order(self):
        candidates = [site("a/First.java", "f"), site("z/Last.java", "g")]
        chosen = select_sites(candidates, {"z/Last.java": 9}, order="ranked")
        self.assertEqual([s["file"] for s in chosen], ["z/Last.java", "a/First.java"])

    def test_reach_beats_inbound(self):
        candidates = [site("a/A.java", "f", reach=4), site("b/B.java", "g", reach=5)]
        chosen = select_sites(candidates, {"a/A.java": 50}, order="ranked")
        self.assertEqual(chosen[0]["file"], "b/B.java")

    def test_per_file_cap_stops_one_class_filling_the_sample(self):
        candidates = [site("a/Big.java", "m%d" % i, start=i, end=i + 5) for i in range(20)]
        self.assertEqual(len(select_sites(candidates, {}, per_file=5, order="ranked")), 5)

    def test_ordering_is_deterministic(self):
        candidates = [site("a/A.java", "f", 1), site("a/A.java", "g", 5)]
        first = [s["function"] for s in select_sites(candidates, {}, order="ranked")]
        second = [s["function"] for s in select_sites(list(reversed(candidates)), {}, order="ranked")]
        self.assertEqual(first, second)

    def test_limit_is_respected(self):
        candidates = [site("f%d.java" % i, "m") for i in range(50)]
        self.assertEqual(len(select_sites(candidates, {}, limit=7, per_file=5, order="ranked")), 7)

    def test_accessors_are_trivial(self):
        for function, body in (
            ("getCount", "int getCount() {\n  return count;\n}"),
            ("setFoo", "void setFoo(int f) {\n  this.f = f;\n}"),
            ("apply", "void apply() {\n  this.state = ready;\n}"),
        ):
            self.assertTrue(is_trivial_accessor(
                {"function": function, "source": body, "lines": [1, 3],
                 "file": "A.java"}), function)

    def test_real_bodies_are_not_trivial(self):
        body = "void send(int f) {\n  if (f > 0) {\n    go();\n  }\n}"
        self.assertFalse(is_trivial_accessor(
            {"function": "send", "source": body, "lines": [1, 5], "file": "A.java"}))


if __name__ == "__main__":
    unittest.main()
