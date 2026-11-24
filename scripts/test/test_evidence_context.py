"""F2: a top-five card shows the lines around the quote, read at report time.

The report is published as one offline file, so the context is baked in when
`report` runs. When the tree is gone — a report read somewhere else, a line
that moved — the card falls back to the quote the finding carried. No error,
because a missing neighbour is not a failed scan.
"""

import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent

sys.path.insert(0, str(SCRIPTS))
from lib.render import CONTEXT_MAX_LINES, render  # noqa: E402

SOURCE = "\n".join([
    "def handler(request):",
    "    # line 2",
    "    # line 3",
    "    # line 4",
    "    # line 5",
    "    # line 6",
    "    payload = request.args['code']",
    "    if payload:",
    "        received = payload.strip()",
    "    eval(payload)",
    "    return received",
    "    # line 12",
    "    # line 13",
    "    # line 14",
    "    # line 15",
]) + "\n"


def build(root, file, line, evidence="eval(payload)"):
    ranked = {
        "repo_name": "r", "tool_version": "0.6.1", "generated_at": "now",
        "confidence_cap": None, "confidence_cap_reason": None,
        "shape": {"verdict": "flat", "c20": 0.5, "n_clusters": 3, "top_n": 1},
        "quadrant": {"counts": {"quick_wins": 1, "batch_2": 0, "free": 0, "skip": 0}},
        "curve": [], "curve_markers": [], "coverage": {},
        "clusters": [{"key": "py-eval", "taxonomy": "code-injection", "class": "defect",
                      "n_sites": 1, "impact": 5.0, "effort": 1.0, "priority": 5.0,
                      "findings": ["d_1"], "message": "eval", "file": file, "line": line}],
        "findings": [{"id": "d_1", "taxonomy": "code-injection", "class": "defect",
                      "file": file, "line": line, "evidence": evidence, "reach": 5,
                      "blast": 5, "silence": 3, "effort": 1, "impact": 5.0,
                      "priority": 5.0, "confidence": "high",
                      "effort_drivers": ["1 file", "0 importers"]}],
        "blocking_security": [], "could_not_determine": ["x"], "redactions": [],
    }
    return render(ranked, {"root": root, "entrypoints": [],
                           "tests": {"present": False}})


class SurroundingLinesTests(unittest.TestCase):
    def test_three_lines_either_side_of_the_cited_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "app.py").write_text(SOURCE, encoding="utf-8")
            html = build(tmp, "app.py", 10)

        self.assertIn('<pre class="context">', html)
        # 7..13 are in; 6 and 14 are out.
        self.assertIn("payload = request.args[&#x27;code&#x27;]", html)
        self.assertIn("# line 13", html)
        self.assertNotIn("# line 6", html)
        self.assertNotIn("# line 14", html)
        self.assertEqual(html.count('class="line'), 7)

    def test_the_cited_line_is_marked(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "app.py").write_text(SOURCE, encoding="utf-8")
            html = build(tmp, "app.py", 10)

        self.assertIn('<span class="line cited"><span class="n">10</span>'
                      '<span class="m">›</span>    eval(payload)</span>', html)
        self.assertEqual(html.count("›"), 1)

    def test_the_block_is_capped_at_seven_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "big.py").write_text(
                "\n".join("line %d" % n for n in range(1, 41)) + "\n", encoding="utf-8")
            html = build(tmp, "big.py", 20)

        self.assertEqual(CONTEXT_MAX_LINES, 7)
        self.assertEqual(html.count('class="line'), 7)
        self.assertIn("line 17", html)
        self.assertIn("line 23", html)
        self.assertNotIn("line 16", html)
        self.assertNotIn("line 24", html)


class FallbackTests(unittest.TestCase):
    def test_missing_file_falls_back_to_the_quoted_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            html = build(tmp, "gone.py", 4, evidence="eval(unknown)")

        self.assertEqual(html.count('class="line'), 1)
        self.assertIn('<span class="line cited">', html)
        self.assertIn("eval(unknown)", html)

    def test_line_out_of_range_falls_back_to_the_quoted_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "app.py").write_text(SOURCE, encoding="utf-8")
            html = build(tmp, "app.py", 999, evidence="eval(shifted)")

        self.assertEqual(html.count('class="line'), 1)
        self.assertIn("eval(shifted)", html)


class EscapingTests(unittest.TestCase):
    def test_html_in_the_source_is_escaped(self):
        source = "\n".join([
            "before = 1",
            "markup = \"<script>alert(1)</script>\"",
            "after = 2",
        ]) + "\n"
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "app.py").write_text(source, encoding="utf-8")
            html = build(tmp, "app.py", 2)

        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)

    def test_a_secret_on_a_neighbouring_line_is_masked(self):
        source = "\n".join([
            "password = \"hunter2hunter2\"",
            "eval(payload)",
        ]) + "\n"
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "app.py").write_text(source, encoding="utf-8")
            html = build(tmp, "app.py", 2)

        self.assertNotIn("hunter2hunter2", html)
        self.assertIn("password", html)


if __name__ == "__main__":
    unittest.main()
