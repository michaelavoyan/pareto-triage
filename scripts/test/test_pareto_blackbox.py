"""Black-box tests for the pareto-triage scoring contract.

These tests never import the implementation. They build throwaway Python
repositories under a temporary directory, drive the documented command line
(gate -> context -> detect -> validate -> rank -> report) and check the
published artifacts against the rules in README.md, SKILL.md and
references/rubric.md.

Phase-2 records are written in the schema from references/prompts.md and are
put through the tool's own `validate` before `rank` sees them, so every score
checked here comes from the tool, not from this file.
"""

import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO_ROOT / "scripts" / "pareto-triage.py"
PY = sys.executable

EPS = 1e-6


def flask_routes(n):
    """A flask app with n trivial POST handlers, h0..h(n-1), and no defects."""
    head = "from flask import Flask, request\n\napp = Flask(__name__)\n\n"
    body = "".join(
        "@app.route('/h{i}', methods=['POST'])\n"
        "def handler_{i}():\n"
        "    data = request.json\n"
        "    return str(data)\n\n".format(i=i)
        for i in range(n)
    )
    return head + body


class Sandbox:
    """A temporary repo plus helpers for one pipeline run."""

    def __init__(self, case):
        self.case = case
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="pareto-blackbox-"))
        case.addCleanup(shutil.rmtree, str(self.root), True)
        self.repo = self.root / "repo"
        self.out = self.repo / "out"
        self._seq = 0
        self._context = None

    # -- files ---------------------------------------------------------
    def add_file(self, relpath, text):
        path = self.repo / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    # -- commands ------------------------------------------------------
    def run(self, *args, expect=0, timeout=60):
        proc = subprocess.run(
            [PY, str(TOOL), *args],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if expect is not None:
            self.case.assertEqual(
                proc.returncode,
                expect,
                msg=(
                    "command {} exited {}\n--- stdout ---\n{}\n--- stderr ---\n{}"
                    .format(" ".join(args), proc.returncode, proc.stdout, proc.stderr)
                ),
            )
        return proc

    def gate(self, *extra, min_loc="1"):
        args = ["gate", str(self.repo)]
        if min_loc is not None:
            args += ["--min-loc", min_loc]
        args += ["--out", str(self.out)] + list(extra)
        return self.run(*args)

    def context(self):
        return self.run("context", str(self.repo))

    def detect(self):
        return self.run("detect", str(self.repo))

    def rank(self, *extra):
        return self.run("rank", str(self.repo), *extra)

    def report(self, *extra, expect=0):
        return self.run("report", str(self.repo), *extra, expect=expect)

    # -- artifacts -----------------------------------------------------
    def load(self, name):
        return json.loads((self.out / name).read_text(encoding="utf-8"))

    def ranked(self):
        return self.load("ranked.json")

    def jsonl(self, name):
        path = self.out / name
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def context_records(self):
        if self._context is None:
            self._context = self.jsonl("context.jsonl")
        return self._context

    def site(self, function):
        for record in self.context_records():
            if record["function"] == function:
                return record
        raise AssertionError("no candidate site for function {!r}".format(function))

    # -- phase 2 -------------------------------------------------------
    def finding(self, function, taxonomy, blast, silence, reach=5,
                evidence="return str(data)"):
        """One schema-conforming phase-2 record, located from context.jsonl."""
        site = self.site(function)
        source = (self.repo / site["file"]).read_text(encoding="utf-8").splitlines()
        start, end = site["lines"]
        line = next(
            n for n in range(start, end + 1) if evidence in source[n - 1]
        )
        self._seq += 1
        return {
            "id": "f_{:08x}".format(self._seq),
            "site_id": site["site_id"],
            "class": "failure-mode",
            "taxonomy": taxonomy,
            "file": site["file"],
            "line": line,
            "evidence": evidence,
            "counter_evidence": "The surrounding guard may already cover this path.",
            "detector": "llm",
            "confidence": "med",
            "reach": reach,
            "blast": blast,
            "silence": silence,
            "call_path": [site["call_path"][0], function],
        }

    def failure_modes(self, records):
        path = self.out / "failure-modes.jsonl"
        path.write_text(
            "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8"
        )
        self.run("validate", str(path), "--repo", str(self.repo))
        return path


# ---------------------------------------------------------------------------
# Documented arithmetic, expressed independently of the tool.
# ---------------------------------------------------------------------------

def documented_impact(blast, silence, reach):
    # rubric 1.0.0: impact = blast x silence / 3, and rubric 1.2.0:
    # reach == 1 -> impact x 0.25.
    impact = blast * silence / 3.0
    if reach == 1:
        impact *= 0.25
    return impact


def documented_verdict(c20, top_median_effort):
    # rubric "Shape" table.
    if c20 >= 0.6:
        if top_median_effort <= 2:
            return "shortcut"
        if top_median_effort >= 4:
            return "concentrated-expensive"
        raise AssertionError(
            "top median effort {} is outside the documented verdict table".format(
                top_median_effort
            )
        )
    if c20 >= 0.3:
        return "moderate"
    return "flat"


def pareto_prefix(ranked, target):
    """Cheapest priority-ordered prefix reaching target x total impact.

    Returns (clusters, effort_share, impact_share).
    """
    clusters = sorted(ranked["clusters"], key=lambda c: c["priority"], reverse=True)
    total_impact = sum(c["impact"] for c in clusters)
    total_effort = sum(c["effort"] for c in clusters)
    cum_impact = 0.0
    cum_effort = 0.0
    for count, cluster in enumerate(clusters, 1):
        cum_impact += cluster["impact"]
        cum_effort += cluster["effort"]
        if cum_impact + EPS >= target * total_impact:
            return count, cum_effort / total_effort, cum_impact / total_impact
    raise AssertionError("target never reached")


def c20_of(ranked):
    clusters = sorted(ranked["clusters"], key=lambda c: c["impact"], reverse=True)
    n_top = max(1, -(-len(clusters) * 1 // 5))  # ceil(20% of clusters)
    total = sum(c["impact"] for c in clusters)
    return sum(c["impact"] for c in clusters[:n_top]) / total, n_top


# ---------------------------------------------------------------------------
# 1. impact = blast x silence / 3, x0.25 at reach == 1
# ---------------------------------------------------------------------------

class ImpactTests(unittest.TestCase):
    def test_impact_formula_for_failure_modes_and_defects(self):
        sandbox = Sandbox(self)
        # One route with an eval defect (detect) plus four judged functions.
        sandbox.add_file(
            "src/api/app.py",
            "from flask import Flask, request\n\napp = Flask(__name__)\n\n"
            "@app.route('/eval', methods=['POST'])\n"
            "def handler_eval():\n"
            "    return str(eval(request.json['x']))\n\n"
            + flask_routes(4).split("\n\n", 2)[2],
        )
        sandbox.gate()
        sandbox.context()
        sandbox.detect()
        sandbox.failure_modes([
            sandbox.finding("handler_0", "swallowed-exception", 5, 3),
            sandbox.finding("handler_1", "missing-timeout", 4, 2),
            sandbox.finding("handler_2", "no-retry", 3, 1),
            sandbox.finding("handler_3", "no-backoff", 2, 3),
        ])
        sandbox.rank()
        ranked = sandbox.ranked()

        defects = [f for f in ranked["findings"] if f["class"] == "defect"]
        self.assertTrue(defects, "expected the eval defect to be detected")
        self.assertGreaterEqual(len(ranked["findings"]), 5)

        for finding in ranked["findings"]:
            expected = documented_impact(
                finding["blast"], finding["silence"], finding["reach"]
            )
            self.assertAlmostEqual(
                finding["impact"],
                round(expected, 4),
                places=3,
                msg="impact mismatch for {} (blast {}, silence {}, reach {})".format(
                    finding.get("rule") or finding["taxonomy"],
                    finding["blast"],
                    finding["silence"],
                    finding["reach"],
                ),
            )
            self.assertGreaterEqual(finding["impact"], 0.0)
            self.assertLessEqual(finding["impact"], 5.0)

    def test_reach_one_quarters_impact(self):
        sandbox = Sandbox(self)
        sandbox.add_file("src/api/app.py", flask_routes(2))
        sandbox.gate()
        sandbox.context()
        sandbox.detect()
        sandbox.failure_modes([
            sandbox.finding("handler_0", "swallowed-exception", 5, 3, reach=1),
            sandbox.finding("handler_1", "missing-timeout", 5, 3, reach=5),
        ])
        sandbox.rank()
        ranked = sandbox.ranked()
        by_id = {f["taxonomy"]: f for f in ranked["findings"]}

        discounted = by_id["swallowed-exception"]
        full = by_id["missing-timeout"]

        self.assertEqual(discounted["reach"], 1)
        self.assertAlmostEqual(discounted["impact"], 1.25, places=3)
        self.assertAlmostEqual(full["impact"], 5.0, places=3)
        # Documented multiplier is exactly 0.25 for reach == 1.
        self.assertAlmostEqual(
            discounted["impact"], full["impact"] * 0.25, places=3
        )


# ---------------------------------------------------------------------------
# 2. priority = impact / effort
# ---------------------------------------------------------------------------

class PriorityTests(unittest.TestCase):
    def mixed_repo(self):
        # One expensive 5-site cluster plus one cheap cluster, so effort values
        # differ from each other and from finding-level effort.
        sandbox = Sandbox(self)
        sandbox.add_file("src/api/app.py", flask_routes(6))
        sandbox.gate()
        sandbox.context()
        sandbox.detect()
        records = [
            sandbox.finding("handler_{}".format(i), "unbounded-query", 3, 3)
            for i in range(5)
        ]
        records.append(sandbox.finding("handler_5", "missing-timeout", 4, 3))
        sandbox.failure_modes(records)
        sandbox.rank()
        return sandbox.ranked()

    def test_finding_priority_is_impact_over_effort(self):
        ranked = self.mixed_repo()
        self.assertTrue(ranked["findings"])
        for finding in ranked["findings"]:
            self.assertAlmostEqual(
                finding["priority"],
                finding["impact"] / finding["effort"],
                places=3,
                msg="finding priority is not impact/effort",
            )

    def test_cluster_priority_is_impact_over_effort(self):
        ranked = self.mixed_repo()
        self.assertEqual(len(ranked["clusters"]), 2)
        for cluster in ranked["clusters"]:
            self.assertGreater(cluster["effort"], 0)
            self.assertAlmostEqual(
                cluster["priority"],
                cluster["impact"] / cluster["effort"],
                places=3,
                msg="cluster priority is not impact/effort",
            )


# ---------------------------------------------------------------------------
# 3. c20 and the four verdicts
# ---------------------------------------------------------------------------

class ShapeTests(unittest.TestCase):
    def test_c20_is_top_twentieth_of_clusters(self):
        taxes = [
            "missing-idempotency",
            "unbounded-query",
            "unbounded-concurrency",
            "missing-boundary-validation",
            "missing-authz",
            "silent-default-fallback",
            "resource-leak",
            "non-atomic-write",
        ]
        records = []
        sandbox = Sandbox(self)
        sandbox.add_file("src/api/app.py", flask_routes(10))
        sandbox.gate()
        sandbox.context()
        sandbox.detect()
        records.append(sandbox.finding("handler_0", "swallowed-exception", 5, 3))
        records.append(sandbox.finding("handler_1", "missing-timeout", 4, 3))
        for i, taxonomy in enumerate(taxes):
            records.append(
                sandbox.finding("handler_{}".format(i + 2), taxonomy, 1, 3)
            )
        sandbox.failure_modes(records)
        sandbox.rank()
        ranked = sandbox.ranked()
        shape = ranked["shape"]

        self.assertEqual(shape["n_clusters"], 10)
        self.assertEqual(shape["top_n"], 2)  # 20% of 10
        self.assertEqual(len(shape["top_keys"]), 2)

        expected_c20, _ = c20_of(ranked)
        self.assertAlmostEqual(shape["c20"], expected_c20, places=3)
        self.assertAlmostEqual(shape["c20"], 9 / 17, places=3)
        # The top set is chosen by impact, not by priority (effort); here they
        # coincide, so also check the keys are exactly the two biggest impacts.
        self.assertEqual(
            sorted(shape["top_keys"]), ["missing-timeout", "swallowed-exception"]
        )

    def test_verdict_shortcut(self):
        sandbox = Sandbox(self)
        sandbox.add_file("src/api/app.py", flask_routes(4))
        sandbox.gate()
        sandbox.context()
        sandbox.detect()
        sandbox.failure_modes([
            sandbox.finding("handler_0", "swallowed-exception", 5, 3),
            sandbox.finding("handler_1", "missing-timeout", 1, 3),
            sandbox.finding("handler_2", "no-retry", 1, 3),
            sandbox.finding("handler_3", "no-backoff", 1, 3),
        ])
        sandbox.rank()
        ranked = sandbox.ranked()
        shape = ranked["shape"]

        self.assertEqual(shape["n_clusters"], 4)
        self.assertAlmostEqual(shape["c20"], 5 / 8, places=3)
        self.assertGreaterEqual(shape["c20"], 0.6)
        self.assertLessEqual(shape["top_median_effort"], 2)
        self.assertEqual(shape["verdict"], "shortcut")
        self.assertEqual(shape["verdict"], documented_verdict(shape["c20"], shape["top_median_effort"]))

    def test_verdict_concentrated_expensive(self):
        sandbox = Sandbox(self)
        sandbox.add_file("src/api/app.py", flask_routes(6))
        sandbox.gate()
        sandbox.context()
        sandbox.detect()
        records = [
            sandbox.finding("handler_{}".format(i), "unbounded-query", 5, 3)
            for i in range(5)
        ]
        records.append(sandbox.finding("handler_5", "missing-timeout", 3, 3))
        # A third cluster keeps the shape verdict meaningful (the rubric needs
        # at least three); its impact is small enough not to enter the top 20%.
        records.append(sandbox.finding("handler_2", "no-retry", 1, 1))
        sandbox.failure_modes(records)
        sandbox.rank()
        ranked = sandbox.ranked()
        shape = ranked["shape"]

        self.assertEqual(shape["n_clusters"], 3)
        # Impact-ordered top set: the 5-site cluster (impact 5.0) beats the
        # single site (impact 3.0). Priority-ordered it would not, since the
        # big cluster also costs 5.2 effort; c20 must ignore effort.
        self.assertEqual(sorted(shape["top_keys"]), ["unbounded-query"])
        self.assertGreaterEqual(shape["c20"], 0.6)
        self.assertGreaterEqual(shape["top_median_effort"], 4)
        self.assertEqual(shape["verdict"], "concentrated-expensive")
        self.assertEqual(shape["verdict"], documented_verdict(shape["c20"], shape["top_median_effort"]))

    def test_verdict_moderate(self):
        sandbox = Sandbox(self)
        sandbox.add_file("src/api/app.py", flask_routes(3))
        sandbox.gate()
        sandbox.context()
        sandbox.detect()
        sandbox.failure_modes([
            sandbox.finding("handler_0", "swallowed-exception", 3, 2),
            sandbox.finding("handler_1", "missing-timeout", 3, 2),
            sandbox.finding("handler_2", "no-retry", 3, 2),
        ])
        sandbox.rank()
        shape = sandbox.ranked()["shape"]

        self.assertEqual(shape["n_clusters"], 3)
        self.assertAlmostEqual(shape["c20"], 1 / 3, places=3)
        self.assertGreaterEqual(shape["c20"], 0.3)
        self.assertLessEqual(shape["c20"], 0.6)
        self.assertEqual(shape["verdict"], "moderate")
        self.assertEqual(shape["verdict"], documented_verdict(shape["c20"], shape["top_median_effort"]))

    def test_verdict_flat(self):
        taxes = [
            "swallowed-exception",
            "missing-timeout",
            "no-retry",
            "no-backoff",
            "missing-idempotency",
        ]
        sandbox = Sandbox(self)
        sandbox.add_file("src/api/app.py", flask_routes(5))
        sandbox.gate()
        sandbox.context()
        sandbox.detect()
        sandbox.failure_modes([
            sandbox.finding("handler_{}".format(i), taxonomy, 3, 2)
            for i, taxonomy in enumerate(taxes)
        ])
        sandbox.rank()
        shape = sandbox.ranked()["shape"]

        self.assertEqual(shape["n_clusters"], 5)
        self.assertAlmostEqual(shape["c20"], 0.2, places=3)
        self.assertLess(shape["c20"], 0.3)
        self.assertEqual(shape["verdict"], "flat")
        self.assertEqual(shape["verdict"], documented_verdict(shape["c20"], shape["top_median_effort"]))


# ---------------------------------------------------------------------------
# 4. pareto point and its shortcut flag
# ---------------------------------------------------------------------------

class ParetoTests(unittest.TestCase):
    def test_pareto_point_is_priority_prefix_for_80_percent(self):
        sandbox = Sandbox(self)
        sandbox.add_file("src/api/app.py", flask_routes(4))
        sandbox.gate()
        sandbox.context()
        sandbox.detect()
        sandbox.failure_modes([
            sandbox.finding("handler_0", "swallowed-exception", 5, 3),
            sandbox.finding("handler_1", "missing-timeout", 1, 3),
            sandbox.finding("handler_2", "no-retry", 1, 3),
            sandbox.finding("handler_3", "no-backoff", 1, 3),
        ])
        sandbox.rank()
        ranked = sandbox.ranked()
        pareto = ranked["pareto"]

        self.assertEqual(pareto["target"], 0.8)
        clusters, effort_share, impact_share = pareto_prefix(ranked, 0.8)
        self.assertEqual(pareto["clusters"], clusters)
        self.assertEqual(pareto["of_clusters"], len(ranked["clusters"]))
        self.assertAlmostEqual(pareto["effort_share"], effort_share, places=3)
        self.assertAlmostEqual(pareto["impact_share"], impact_share, places=3)
        # 5 impact, then three 1-impact clusters: 80% of 8 needs three clusters.
        self.assertEqual(pareto["clusters"], 3)
        self.assertAlmostEqual(pareto["effort_share"], 0.75, places=3)
        self.assertFalse(pareto["shortcut"])

    def test_pareto_shortcut_true_only_at_most_half_effort(self):
        # 5 impact on a cheap cluster, four 1/3-impact clusters: 80% of the
        # impact costs 2 of 10 effort units.
        sandbox = Sandbox(self)
        sandbox.add_file("src/api/app.py", flask_routes(5))
        sandbox.gate()
        sandbox.context()
        sandbox.detect()
        sandbox.failure_modes([
            sandbox.finding("handler_0", "swallowed-exception", 5, 3),
            sandbox.finding("handler_1", "missing-timeout", 1, 1),
            sandbox.finding("handler_2", "no-retry", 1, 1),
            sandbox.finding("handler_3", "no-backoff", 1, 1),
            sandbox.finding("handler_4", "missing-idempotency", 1, 1),
        ])
        sandbox.rank()
        ranked = sandbox.ranked()
        pareto = ranked["pareto"]

        clusters, effort_share, impact_share = pareto_prefix(ranked, 0.8)
        self.assertEqual(pareto["clusters"], clusters)
        self.assertAlmostEqual(pareto["effort_share"], effort_share, places=3)
        self.assertAlmostEqual(pareto["impact_share"], impact_share, places=3)
        self.assertLessEqual(pareto["effort_share"], 0.5 + EPS)
        self.assertTrue(pareto["shortcut"])
        # The 80% row of the ladder is the same measurement as pareto.
        row = ranked["pareto_ladder"][-1]
        self.assertEqual(row["target"], 0.8)
        self.assertEqual(row["clusters"], pareto["clusters"])
        self.assertAlmostEqual(row["effort_share"], pareto["effort_share"], places=3)
        self.assertAlmostEqual(row["impact_share"], pareto["impact_share"], places=3)


# ---------------------------------------------------------------------------
# 5. the 50/70/80 ladder is monotonic
# ---------------------------------------------------------------------------

class LadderTests(unittest.TestCase):
    def test_ladder_targets_and_monotonicity(self):
        taxes = [
            "missing-idempotency",
            "unbounded-query",
            "unbounded-concurrency",
            "missing-boundary-validation",
            "missing-authz",
            "silent-default-fallback",
            "resource-leak",
            "non-atomic-write",
        ]
        sandbox = Sandbox(self)
        sandbox.add_file("src/api/app.py", flask_routes(10))
        sandbox.gate()
        sandbox.context()
        sandbox.detect()
        records = [
            sandbox.finding("handler_0", "swallowed-exception", 5, 3),
            sandbox.finding("handler_1", "missing-timeout", 4, 3),
        ]
        records += [
            sandbox.finding("handler_{}".format(i + 2), taxonomy, 1, 3)
            for i, taxonomy in enumerate(taxes)
        ]
        sandbox.failure_modes(records)
        sandbox.rank()
        ranked = sandbox.ranked()
        ladder = ranked["pareto_ladder"]

        self.assertEqual([row["target"] for row in ladder], [0.5, 0.7, 0.8])

        previous_effort = -1.0
        previous_impact = -1.0
        for row in ladder:
            clusters, effort_share, impact_share = pareto_prefix(ranked, row["target"])
            self.assertEqual(row["clusters"], clusters)
            self.assertEqual(row["of_clusters"], len(ranked["clusters"]))
            self.assertAlmostEqual(row["effort_share"], effort_share, places=3)
            self.assertAlmostEqual(row["impact_share"], impact_share, places=3)
            # "more impact never costs less"
            self.assertGreaterEqual(row["effort_share"], previous_effort - EPS)
            self.assertGreaterEqual(row["impact_share"], previous_impact - EPS)
            self.assertGreaterEqual(row["impact_share"], row["target"] - 1e-3)
            previous_effort = row["effort_share"]
            previous_impact = row["impact_share"]


# ---------------------------------------------------------------------------
# 6. refusals
# ---------------------------------------------------------------------------

class RefusalTests(unittest.TestCase):
    def test_foreign_tool_version_ranking_produces_no_report(self):
        sandbox = Sandbox(self)
        sandbox.add_file(
            "src/api/app.py",
            "from flask import Flask, request\n\napp = Flask(__name__)\n\n"
            "@app.route('/e', methods=['POST'])\n"
            "def handler():\n"
            "    return str(eval(request.json['x']))\n",
        )
        sandbox.gate()
        sandbox.detect()
        sandbox.rank()
        self.assertFalse((sandbox.out / "report.html").exists())

        ranked_path = sandbox.out / "ranked.json"
        ranked = json.loads(ranked_path.read_text(encoding="utf-8"))
        ranked["tool_version"] = "0.0.0-some-other-tool"
        ranked_path.write_text(json.dumps(ranked), encoding="utf-8")

        proc = sandbox.report(expect=None)
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(
            (sandbox.out / "report.html").exists(),
            "a ranking from another tool version produced report.html",
        )
        self.assertFalse(
            (sandbox.out / "report.json").exists(),
            "a ranking from another tool version produced report.json",
        )
        self.assertIn("refus", (proc.stdout + proc.stderr).lower())

    def test_gate_refusal_produces_no_report(self):
        sandbox = Sandbox(self)
        # No route, CLI command, or cron job: no reachability signal.
        sandbox.add_file("src/util.py", "def add(a, b):\n    return a + b\n")
        proc = sandbox.run(
            "gate", str(sandbox.repo), "--min-loc", "1", "--out", str(sandbox.out),
            expect=None,
        )
        self.assertNotEqual(proc.returncode, 0)
        scope = sandbox.load("scope.json")
        self.assertFalse(scope["gate"]["ok"])
        self.assertTrue(scope["gate"]["reasons"])

        rank = sandbox.run("rank", str(sandbox.repo), expect=None)
        self.assertNotEqual(rank.returncode, 0)
        report = sandbox.report(expect=None)
        self.assertNotEqual(report.returncode, 0)
        self.assertFalse((sandbox.out / "ranked.json").exists())
        self.assertFalse((sandbox.out / "report.html").exists())
        self.assertFalse((sandbox.out / "report.json").exists())

    def test_gate_refuses_repo_below_default_line_threshold(self):
        sandbox = Sandbox(self)
        sandbox.add_file(
            "src/app.py",
            "from flask import Flask\n\napp = Flask(__name__)\n\n"
            "@app.route('/x')\ndef handler():\n    return 'ok'\n",
        )
        proc = sandbox.run(
            "gate", str(sandbox.repo), "--out", str(sandbox.out), expect=None
        )
        self.assertNotEqual(proc.returncode, 0)
        scope = sandbox.load("scope.json")
        self.assertFalse(scope["gate"]["ok"])
        reasons = " ".join(scope["gate"]["reasons"])
        self.assertIn("10,000", reasons, "documented minimum is 10k non-blank lines")
        rank = sandbox.run("rank", str(sandbox.repo), expect=None)
        self.assertNotEqual(rank.returncode, 0)
        report = sandbox.report(expect=None)
        self.assertNotEqual(report.returncode, 0)
        self.assertFalse((sandbox.out / "report.html").exists())

    def test_reach_zero_finding_is_dropped_before_clustering(self):
        sandbox = Sandbox(self)
        sandbox.add_file("src/api/app.py", flask_routes(1))
        sandbox.gate()
        sandbox.context()
        sandbox.detect()
        sandbox.failure_modes([
            sandbox.finding("handler_0", "swallowed-exception", 5, 3, reach=0),
        ])
        sandbox.rank()
        ranked = sandbox.ranked()
        self.assertEqual(ranked["findings"], [])
        self.assertEqual(ranked["clusters"], [])


if __name__ == "__main__":
    unittest.main()
