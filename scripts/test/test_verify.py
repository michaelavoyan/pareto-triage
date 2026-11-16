import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
CLI = SCRIPTS / "pareto-triage.py"
FIXTURES = SCRIPTS.parent / "fixtures"


def run(args, cwd=None):
    return subprocess.run([sys.executable, str(CLI)] + [str(a) for a in args],
                          capture_output=True, text=True, cwd=cwd)


def git(repo, *args):
    return subprocess.run(["git"] + list(args), cwd=str(repo), capture_output=True, text=True)


@unittest.skipUnless(shutil.which("git"), "git is required for verification")
class VerifyTests(unittest.TestCase):
    def make_repo(self, tmp):
        """A git repo holding the express fixture at its root."""
        repo = Path(tmp) / "repo"
        shutil.copytree(str(FIXTURES / "express-app"), str(repo))
        git(repo, "init", "-q")
        git(repo, "add", "-A")
        git(repo, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-qm", "fixture")
        return repo

    def pipeline(self, repo, out):
        run(["gate", repo, "--min-loc", "1", "--out", out])
        run(["context", repo, "--out", out])
        run(["detect", repo, "--out", out])
        result = run(["rank", repo, "--out", out])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_refuses_without_a_ranking(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            out = Path(tmp) / "out"
            run(["gate", repo, "--min-loc", "1", "--out", out])
            result = run(["verify", repo, "--out", out])
            self.assertEqual(result.returncode, 2)
            self.assertIn("run: pareto-triage rank", result.stderr)

    def test_refuses_outside_a_git_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "plain"
            shutil.copytree(str(FIXTURES / "express-app"), str(repo))
            out = Path(tmp) / "out"
            self.pipeline(repo, out)
            env_repo = str(repo)
            # A plain directory inside no repository must be refused.
            result = subprocess.run([sys.executable, str(CLI), "verify", env_repo, "--out", str(out)],
                                    capture_output=True, text=True,
                                    env={**os.environ, "GIT_CEILING_DIRECTORIES": str(Path(tmp).parent)})
            if result.returncode == 0:
                self.skipTest("directory is inside an enclosing git repository")
            self.assertEqual(result.returncode, 2)
            self.assertIn("cannot verify", result.stderr)

    def test_unverified_when_no_probe_is_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            out = Path(tmp) / "out"
            self.pipeline(repo, out)
            result = run(["verify", repo, "--out", out])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads((out / "verify.json").read_text())
            self.assertEqual(payload["counts"].get("unverified"), len(payload["clusters"]))
            self.assertEqual(payload["suite"]["status"], "not-run")
            for record in payload["clusters"]:
                self.assertIn("no probe", record["reason"])

    def test_probe_that_fails_marks_the_cluster_reproduced(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            out = Path(tmp) / "out"
            self.pipeline(repo, out)
            ranked = json.loads((out / "ranked.json").read_text())
            key = ranked["clusters"][0]["key"]

            probes = out / "probes"
            probes.mkdir()
            (probes / (key + ".sh")).write_text("#!/bin/sh\nprintf 'boom\\n' >&2\nexit 1\n")

            result = run(["verify", repo, "--out", out])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads((out / "verify.json").read_text())
            record = next(r for r in payload["clusters"] if r["cluster"] == key)
            self.assertEqual(record["status"], "reproduced")
            self.assertEqual(record["exit"], 1)
            self.assertIn("boom", record["output_tail"])

    def test_probe_that_passes_is_not_reproduced(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            out = Path(tmp) / "out"
            self.pipeline(repo, out)
            key = json.loads((out / "ranked.json").read_text())["clusters"][0]["key"]

            probes = out / "probes"
            probes.mkdir()
            (probes / (key + ".sh")).write_text("#!/bin/sh\nexit 0\n")

            result = run(["verify", repo, "--out", out])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads((out / "verify.json").read_text())
            record = next(r for r in payload["clusters"] if r["cluster"] == key)
            self.assertEqual(record["status"], "not-reproduced")

    def test_worktree_is_cleaned_up_and_tree_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            out = Path(tmp) / "out"
            self.pipeline(repo, out)
            before = git(repo, "status", "--porcelain").stdout
            result = run(["verify", repo, "--out", out])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(git(repo, "status", "--porcelain").stdout, before)
            self.assertEqual(git(repo, "worktree", "list").stdout.count("\n"), 1)
            self.assertNotIn(str(repo), json.dumps(json.loads((out / "verify.json").read_text())))

    def test_verify_refuses_a_stale_ranking(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            out = Path(tmp) / "out"
            self.pipeline(repo, out)
            (repo / "src" / "billing.ts").write_text("export const x = 1\n")
            result = run(["verify", repo, "--out", out])
            self.assertEqual(result.returncode, 1)
            self.assertIn("stale", result.stderr)


if __name__ == "__main__":
    unittest.main()
