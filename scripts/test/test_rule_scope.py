"""The two scopes a rule must prove before it fires.

Secret findings mean committed secrets: an untracked, gitignored `.env` is not
part of the repository. A shell-injection finding means a shell call: `exec(`
alone is a name shared with database handles and process pools.

The `.env` fixtures are built in temp directories rather than committed under
`fixtures/`: this repository ignores `.env`, so a committed tracked `.env`
cannot exist without force-adding it. Building the git state per test also lets
one fixture be tracked and the same bytes be untracked.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
CLI = SCRIPTS / "pareto-triage.py"

sys.path.insert(0, str(SCRIPTS))
from lib.rules import detect_defects  # noqa: E402

APP = (
    "def main():\n"
    "    print('ok')\n"
    "\n"
    "\n"
    "if __name__ == '__main__':\n"
    "    main()\n"
)

ENV = "DB_PASSWORD=hunter2hunter2\n"
AWS = "AKIAIOSFODNN7EXAMPLE"


def run(args, env=None):
    return subprocess.run([sys.executable, str(CLI)] + [str(a) for a in args],
                          capture_output=True, text=True, env=env)


def git(repo, *args):
    result = subprocess.run(["git", "-C", str(repo)] + list(args),
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError("git %s failed: %s" % (" ".join(args), result.stderr))


class SecretScopeTests(unittest.TestCase):
    def make_repo(self, tmp):
        repo = Path(tmp) / "repo"
        (repo / "src").mkdir(parents=True)
        (repo / "src" / "app.py").write_text(APP, encoding="utf-8")
        (repo / ".env").write_text(ENV, encoding="utf-8")
        return repo

    def init_git(self, repo):
        git(repo, "init", "-q")

    def gate_and_detect(self, repo, tmp, env=None):
        out = Path(tmp) / "out"
        gate = run(["gate", repo, "--min-loc", "1", "--out", out], env=env)
        self.assertEqual(gate.returncode, 0, gate.stdout + gate.stderr)
        detect = run(["detect", repo, "--out", out], env=env)
        self.assertEqual(detect.returncode, 0, detect.stdout + detect.stderr)
        scope = json.loads((out / "scope.json").read_text(encoding="utf-8"))
        findings = [json.loads(line) for line in
                    (out / "defects.jsonl").read_text(encoding="utf-8").splitlines() if line]
        return scope, detect.stdout, findings

    def test_a_tracked_env_fires(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            self.init_git(repo)
            git(repo, "add", ".env", "src/app.py")

            scope, stdout, findings = self.gate_and_detect(repo, tmp)

        self.assertTrue(scope["secrets"]["tracked_only"], scope["secrets"])
        self.assertIn("git-tracked config files only", stdout)
        self.assertEqual([(f["file"], f["rule"]) for f in findings],
                         [(".env", "cfg-secret-generic")])

    def test_an_untracked_env_is_silent_and_named_as_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            self.init_git(repo)
            git(repo, "add", "src/app.py")

            scope, stdout, findings = self.gate_and_detect(repo, tmp)

        self.assertTrue(scope["secrets"]["tracked_only"], scope["secrets"])
        self.assertIn("1 untracked skipped", stdout)
        self.assertEqual(findings, [])
        # No tracked config file ran the rule, so it is absent rather than a
        # reported zero: a zero would claim the file was read and came back clean.
        self.assertNotIn("cfg-secret-generic", stdout)

    def test_a_source_secret_fires_whether_tracked_or_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            self.init_git(repo)
            git(repo, "add", "src/app.py")
            # Untracked source: the config scope must not reach it.
            (repo / "src" / "leak.py").write_text("AWS = '%s'\n" % AWS, encoding="utf-8")

            _, _, findings = self.gate_and_detect(repo, tmp)

        self.assertEqual([(f["file"], f["rule"]) for f in findings],
                         [("src/leak.py", "py-secret-aws")])

    def test_a_non_git_tree_scans_every_config_file_and_records_the_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)

            scope, stdout, findings = self.gate_and_detect(repo, tmp)

        self.assertFalse(scope["secrets"]["tracked_only"], scope["secrets"])
        self.assertIn("not inside a git work tree", scope["secrets"]["reason"])
        self.assertIn("every config file", stdout)
        self.assertEqual([(f["file"], f["rule"]) for f in findings],
                         [(".env", "cfg-secret-generic")])

    def test_missing_git_scans_every_config_file_and_records_the_reason(self):
        with tempfile.TemporaryDirectory() as empty_path, tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            env = dict(os.environ)
            env["PATH"] = empty_path

            scope, stdout, findings = self.gate_and_detect(repo, tmp, env=env)

        self.assertFalse(scope["secrets"]["tracked_only"], scope["secrets"])
        self.assertIn("git is not installed", scope["secrets"]["reason"])
        self.assertEqual([(f["file"], f["rule"]) for f in findings],
                         [(".env", "cfg-secret-generic")])


class JavaScriptShellCallTests(unittest.TestCase):
    """`exec(` is a shell call only when the file imported child_process."""

    @staticmethod
    def js(text):
        return detect_defects([{"rel": "src/run.ts", "ext": ".ts", "text": text}])[0]

    def rules(self, text):
        return [(f["rule"], f["line"]) for f in self.js(text)]

    def test_a_database_exec_is_not_a_shell_call(self):
        # `db.exec` on a SQLite handle is not a shell, and no rule claims a SQL
        # template: the SQL rule was withdrawn for zero incidence.
        self.assertEqual(self.rules(
            "import { DatabaseSync } from 'node:sqlite';\n"
            "const db = new DatabaseSync('app.db');\n"
            "db.exec(`SELECT * FROM t WHERE id = ${id}`);\n"),
            [])

    def test_exec_without_a_child_process_import_is_silent(self):
        self.assertEqual(self.rules("exec(`rm -rf ${dir}`);\n"), [])

    def test_exec_from_child_process_fires(self):
        text = ("import { exec } from 'node:child_process';\n"
                "exec(`rm -rf ${dir}`);\n")
        self.assertEqual(self.rules(text), [("js-exec-interp", 2)])

    def test_require_and_exec_sync_fire(self):
        text = ("const { execSync } = require('child_process');\n"
                "execSync(`git checkout ${branch}`);\n")
        self.assertEqual(self.rules(text), [("js-exec-interp", 2)])

    def test_exec_file_needs_a_shell_on_the_same_line(self):
        import_line = "import { execFile } from 'child_process';\n"
        self.assertEqual(self.rules(import_line + "execFile(`/bin/rm ${path}`);\n"), [])
        self.assertEqual(
            self.rules(import_line + "execFile(`/bin/rm ${path}`, { shell: true });\n"),
            [("js-exec-interp", 2)])

    def test_spawn_with_an_interpolated_argument_is_not_a_shell_string(self):
        text = ("import { spawn } from 'child_process';\n"
                "spawn('rm', [`-rf ${dir}`]);\n")
        self.assertEqual(self.rules(text), [])


if __name__ == "__main__":
    unittest.main()
