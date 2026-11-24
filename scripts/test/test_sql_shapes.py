"""The SQL shapes no rule may fire on.

`js-sql-template` was withdrawn for zero incidence on both measured corpora;
its silent shapes stay as a fixture so the boundary it drew is still asserted.
The file is scanned through the real pipeline, so a new rule that starts
matching a bound query fails here.
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
FIXTURES = SCRIPTS.parent / "fixtures"
SILENT_FILE = "src/sql.ts"

sys.path.insert(0, str(SCRIPTS))
from lib.rules import META, _js_defects  # noqa: E402


def run(args):
    return subprocess.run([sys.executable, str(CLI)] + [str(a) for a in args],
                          capture_output=True, text=True)


class SilentShapesInSource(unittest.TestCase):
    def test_a_parameter_array_is_silent(self):
        self.assertEqual(_js_defects("db.query(`SELECT * FROM t WHERE id = ?`, [id])\n"), [])

    def test_placeholder_text_with_a_values_argument_is_silent(self):
        self.assertEqual(_js_defects("db.query('SELECT * FROM t WHERE id = ?', [id])\n"), [])

    def test_a_receiver_that_is_not_a_database_is_silent(self):
        text = "api.query(`query { job(term: \"${term}\") { id } }`)\n"
        self.assertEqual(_js_defects(text), [])

    def test_no_rule_claims_the_sql_rule_id(self):
        self.assertNotIn("js-sql-template", META)


class SilentFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        out = Path(cls._tmp.name)
        gate = run(["gate", FIXTURES / "express-app", "--min-loc", "1", "--out", out])
        assert gate.returncode == 0, gate.stdout + gate.stderr
        detect = run(["detect", FIXTURES / "express-app", "--out", out])
        assert detect.returncode == 0, detect.stdout + detect.stderr
        cls.findings = [json.loads(line) for line in
                        (out / "defects.jsonl").read_text().splitlines() if line.strip()]

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_the_sql_shapes_produce_no_finding_from_any_rule(self):
        hits = [(f["rule"], f["line"]) for f in self.findings
                if f["file"] == SILENT_FILE]
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
