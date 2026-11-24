"""`js-sql-template`: the SQL text is assembled from values.

The rule has two scopes to prove before it fires: the call reaches a database
(the receiver names one, or the file imports a SQL driver), and the values are
not passed separately. The negative cases below are the ones that made the
rule narrow enough to ship.
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

sys.path.insert(0, str(SCRIPTS))
from lib.rules import _js_defects, META  # noqa: E402


def rules(text, name="app.ts"):
    """Rules that fire in one source string, in file order."""
    return [rule for rule, _line, _evidence in _js_defects(text)]


def run(args):
    return subprocess.run([sys.executable, str(CLI)] + [str(a) for a in args],
                          capture_output=True, text=True)


class FiringShapes(unittest.TestCase):
    def test_a_template_passed_to_db_query_fires(self):
        self.assertEqual(rules("db.query(`SELECT * FROM jobs WHERE id = '${id}'`)\n"),
                         ["js-sql-template"])

    def test_execute_and_raw_fire_too(self):
        text = (
            "import knex from 'knex'\n"
            "db.execute(`DELETE FROM jobs WHERE id = '${id}'`)\n"
            "knex.raw(`SELECT * FROM scores WHERE score > ${score}`)\n"
        )
        self.assertEqual(rules(text), ["js-sql-template", "js-sql-template"])

    def test_a_sql_driver_import_makes_a_plain_receiver_count(self):
        text = (
            "import knex from 'knex'\n"
            "pool.query(`SELECT * FROM t WHERE id = ${id}`)\n"
        )
        self.assertEqual(rules(text), ["js-sql-template"])

    def test_a_callback_second_argument_does_not_hide_the_interpolation(self):
        text = "db.query(`SELECT * FROM t WHERE id = ${id}`, (err, rows) => rows)\n"
        self.assertEqual(rules(text), ["js-sql-template"])

    def test_the_rule_is_in_the_meta_table(self):
        self.assertEqual(META["js-sql-template"],
                         ("sql-injection", 5, 2,
                          "SQL text built from a template literal carries its values into the query"))


class SilentShapes(unittest.TestCase):
    def test_a_parameter_array_is_silent(self):
        self.assertEqual(rules("db.query(`SELECT * FROM t WHERE id = ?`, [id])\n"), [])

    def test_placeholder_text_with_a_values_argument_is_silent(self):
        self.assertEqual(rules("db.query('SELECT * FROM t WHERE id = ?', [id])\n"), [])

    def test_a_receiver_that_is_not_a_database_is_silent(self):
        text = "api.query(`query { job(term: \"${term}\") { id } }`)\n"
        self.assertEqual(rules(text), [])

    def test_a_bare_call_is_silent(self):
        self.assertEqual(rules("query(`SELECT * FROM t WHERE id = ${id}`)\n"), [])

    def test_a_template_without_interpolation_is_silent(self):
        self.assertEqual(rules("db.query(`SELECT * FROM t WHERE id = 1`)\n"), [])

    def test_a_commented_call_is_silent(self):
        self.assertEqual(rules("// db.query(`SELECT * FROM t WHERE id = ${id}`)\n"), [])

    def test_a_braced_expression_with_a_nested_template_is_one_hit(self):
        text = "db.query(`SELECT * FROM t WHERE id = ${values.map((v) => `${v}`)}\n`)\n"
        self.assertEqual(rules(text), ["js-sql-template"])


class FixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls._tmp.name)
        for command in (["gate", FIXTURES / "express-app", "--min-loc", "1", "--out", cls.out],
                        ["detect", FIXTURES / "express-app", "--out", cls.out]):
            result = run(command)
            assert result.returncode == 0, result.stdout + result.stderr
        cls.findings = [json.loads(line) for line in
                        (cls.out / "defects.jsonl").read_text().splitlines() if line.strip()]

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_the_fixture_fires_on_exactly_the_three_unbound_queries(self):
        hits = [(f["file"], f["line"]) for f in self.findings
                if f["rule"] == "js-sql-template"]
        self.assertEqual(hits, [("src/sql-raw.ts", 5),
                                ("src/sql.ts", 6), ("src/sql.ts", 10)])

    def test_findings_carry_the_documented_axes(self):
        for finding in self.findings:
            if finding["rule"] != "js-sql-template":
                continue
            self.assertEqual((finding["taxonomy"], finding["blast"], finding["silence"]),
                             ("sql-injection", 5, 2))
            self.assertEqual(finding["class"], "defect")
            self.assertEqual(finding["detector"], "tool")

    def test_evidence_is_the_verbatim_line(self):
        source = (FIXTURES / "express-app" / "src" / "sql.ts").read_text()
        lines = source.split("\n")
        for finding in self.findings:
            if finding["rule"] == "js-sql-template" and finding["file"] == "src/sql.ts":
                self.assertEqual(finding["evidence"], lines[finding["line"] - 1].strip())


class RejectedKotlinTemplate(unittest.TestCase):
    """Kotlin string templates measured 0/12 on Signal-Android; the branch is out.

    `fixtures/jvm-rules/.../SqlTemplate.kt` holds the shape: a `$id` in a value
    position and a bound counterpart. Both stay silent because every real hit
    was an identifier (table or column) that cannot be bound with `?`.
    """

    def test_the_jvm_rule_stays_silent_on_the_kotlin_template_fixture(self):
        source = (FIXTURES / "jvm-rules" / "src" / "main" / "kotlin" / "com" / "acme"
                  / "SqlTemplate.kt").read_text()
        self.assertEqual(_jvm_rules_in(source), [])


def _jvm_rules_in(text):
    from lib.rules import _jvm_defects
    return [rule for rule, _line, _evidence in _jvm_defects(text)]


if __name__ == "__main__":
    unittest.main()
