"""js-unvalidated-input: request values that reach a DB or shell sink."""

import posixpath
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
FIXTURES = SCRIPTS.parent / "fixtures" / "express-app"

sys.path.insert(0, str(SCRIPTS))
from lib.rules import detect_defects  # noqa: E402


def source(rel, text):
    return {"rel": rel, "ext": posixpath.splitext(rel)[1], "text": text}


class UnvalidatedInputTests(unittest.TestCase):
    def rules(self, text, rel="src/routes.ts"):
        findings, _ = detect_defects([source(rel, text)])
        return [(f["rule"], f["line"], f["evidence"]) for f in findings]

    def test_body_query_and_params_reach_a_db_sink(self):
        text = (
            "const router = express.Router()\n"
            "router.post('/jobs', (req, res) => {\n"
            "  db.query('SELECT * FROM jobs WHERE id = ' + req.body.id)\n"
            "  db.prepare('DELETE FROM jobs WHERE id = ?').run(req.params.id)\n"
            "  db.run('SELECT * FROM jobs WHERE q = ' + req.query.q)\n"
            "})\n"
        )
        self.assertEqual([rule for rule, _, _ in self.rules(text)],
                         ["js-unvalidated-input"] * 3)

    def test_an_alias_carries_the_taint_to_the_sink(self):
        text = (
            "const router = express.Router()\n"
            "router.get('/jobs', (req, res) => {\n"
            "  const limit = req.query.limit\n"
            "  db.query('SELECT * FROM jobs LIMIT ' + limit)\n"
            "})\n"
        )
        self.assertEqual([(rule, line) for rule, line, _ in self.rules(text)],
                         [("js-unvalidated-input", 4)])

    def test_a_validator_before_the_sink_silences_the_file(self):
        text = (
            "import { z } from 'zod'\n"
            "const router = express.Router()\n"
            "router.post('/jobs', (req, res) => {\n"
            "  db.query('SELECT * FROM jobs WHERE id = ' + req.body.id)\n"
            "})\n"
        )
        self.assertEqual(self.rules(text), [])

    def test_a_parsing_call_is_the_validation_for_a_scalar(self):
        text = (
            "const router = express.Router()\n"
            "router.get('/jobs', (req, res) => {\n"
            "  db.query('SELECT * FROM jobs LIMIT ' + Number(req.query.limit))\n"
            "  db.run('SELECT * FROM jobs LIMIT ' + parseInt(req.query.limit, 10))\n"
            "  db.exec('DELETE FROM jobs WHERE id = ' + JSON.parse(req.body.id))\n"
            "})\n"
        )
        self.assertEqual(self.rules(text), [])

    def test_a_file_without_a_route_registration_is_quiet(self):
        text = (
            "export function read(req, db) {\n"
            "  return db.query('SELECT * FROM jobs WHERE id = ' + req.body.id)\n"
            "}\n"
        )
        self.assertEqual(self.rules(text), [])

    def test_a_shell_sink_requires_child_process(self):
        body = (
            "const router = express.Router()\n"
            "router.post('/render', (req, res) => {\n"
            "  exec('convert ' + req.body.path)\n"
            "})\n"
        )
        self.assertEqual(self.rules(body), [])
        imported = "import { exec } from 'child_process'\n" + body
        self.assertEqual([(rule, line) for rule, line, _ in self.rules(imported)],
                         [("js-unvalidated-input", 4)])

    def test_the_express_fixture_keeps_the_validated_file_silent(self):
        findings, _ = detect_defects([
            {"rel": "src/unvalidated.ts", "ext": ".ts",
             "text": (FIXTURES / "src" / "unvalidated.ts").read_text(encoding="utf-8")},
            {"rel": "src/validated.ts", "ext": ".ts",
             "text": (FIXTURES / "src" / "validated.ts").read_text(encoding="utf-8")},
        ])
        by_file = {}
        for finding in findings:
            by_file.setdefault(finding["file"], []).append(finding["rule"])
        self.assertEqual(by_file.get("src/validated.ts", []), [])
        self.assertEqual(by_file["src/unvalidated.ts"], ["js-unvalidated-input"] * 3)


if __name__ == "__main__":
    unittest.main()
