import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
CLI = SCRIPTS / "pareto-triage.py"

sys.path.insert(0, str(SCRIPTS))
from lib.verify import compare  # noqa: E402


def run(args, cwd=None):
    return subprocess.run([sys.executable, str(CLI)] + [str(a) for a in args],
                          capture_output=True, text=True, cwd=cwd)


def git(repo, *args):
    return subprocess.run(["git"] + list(args), cwd=str(repo), capture_output=True, text=True)


class CompareTests(unittest.TestCase):
    def test_red_then_green_is_fixed(self):
        self.assertEqual(compare({"exit": 1}, {"exit": 0})[0], "fixed")

    def test_green_before_the_patch_proves_nothing(self):
        self.assertEqual(compare({"exit": 0}, {"exit": 0})[0], "not-reproduced")

    def test_still_red_is_inconclusive(self):
        self.assertEqual(compare({"exit": 1}, {"exit": 1})[0], "inconclusive")

    def test_suspicion_is_a_flag_not_a_verdict(self):
        # A silent, instant failure can be legitimate; the flag is recorded on the
        # record so a reader can judge, but it must not silently downgrade a fix.
        self.assertEqual(compare({"exit": 1, "suspicious": "instant", "reason": "x"},
                                 {"exit": 0})[0], "fixed")


class FixPipelineTests(unittest.TestCase):
    def make_repo(self, tmp):
        repo = Path(tmp) / "repo"
        repo.mkdir()
        (repo / "app.py").write_text(
            "import subprocess\n\n\n"
            "def run(cmd):\n    return eval(cmd)\n\n\n"
            "if __name__ == '__main__':\n    run('1 + 1')\n")
        git(repo, "init", "-q")
        git(repo, "add", "-A")
        git(repo, "-c", "user.email=t@e.com", "-c", "user.name=t", "commit", "-qm", "base")
        return repo

    def pipe(self, repo, out):
        for command in (["gate", repo, "--min-loc", "1", "--out", out],
                        ["context", repo, "--out", out],
                        ["detect", repo, "--out", out],
                        ["rank", repo, "--out", out]):
            result = run(command)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def probe(self, out, key, body):
        probes = out / "probes"
        probes.mkdir(parents=True, exist_ok=True)
        path = probes / (key + ".sh")
        path.write_text(body)
        return path

    def make_patch(self, repo, tmp, replacement):
        (repo / "app.py").write_text((repo / "app.py").read_text().replace("eval(cmd)", replacement))
        patch = Path(tmp) / "fix.diff"
        patch.write_text(git(repo, "diff").stdout)
        git(repo, "checkout", "--", "app.py")
        return patch

    def test_red_then_green_marks_the_cluster_fixed(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            out = Path(tmp) / "out"
            self.pipe(repo, out)
            key = json.loads((out / "ranked.json").read_text())["clusters"][0]["key"]
            self.probe(out, key, '#!/bin/sh\ngrep -q "eval(cmd)" app.py && exit 1\nexit 0\n')
            patch = self.make_patch(repo, tmp, "int(cmd)")

            result = run(["verify", repo, "--out", out, "--fix", patch])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads((out / "verify.json").read_text())
            record = next(r for r in payload["clusters"] if r["cluster"] == key)
            self.assertEqual(record["status"], "fixed")
            self.assertEqual(record["before"]["exit"], 1)
            self.assertEqual(record["after"]["exit"], 0)
            self.assertTrue(payload["fix"]["applied"])
            self.assertIn("red to green", payload["note"])

    def test_patch_that_does_not_apply_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            out = Path(tmp) / "out"
            self.pipe(repo, out)
            key = json.loads((out / "ranked.json").read_text())["clusters"][0]["key"]
            self.probe(out, key, "#!/bin/sh\nexit 1\n")
            bad = Path(tmp) / "bad.diff"
            bad.write_text("--- a/nope\n+++ b/nope\n@@ -1 +1 @@\n-x\n+y\n")

            result = run(["verify", repo, "--out", out, "--fix", bad])
            self.assertEqual(result.returncode, 2)
            self.assertIn("cannot apply the patch", result.stderr)
            self.assertFalse((out / "verify.json").exists())

    def test_probe_that_passes_before_the_patch_proves_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            out = Path(tmp) / "out"
            self.pipe(repo, out)
            key = json.loads((out / "ranked.json").read_text())["clusters"][0]["key"]
            self.probe(out, key, "#!/bin/sh\nexit 0\n")
            patch = self.make_patch(repo, tmp, "int(cmd)")

            result = run(["verify", repo, "--out", out, "--fix", patch])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            record = next(r for r in json.loads((out / "verify.json").read_text())["clusters"]
                          if r["cluster"] == key)
            self.assertEqual(record["status"], "not-reproduced")

    def test_patch_that_does_not_fix_it_is_inconclusive(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            out = Path(tmp) / "out"
            self.pipe(repo, out)
            key = json.loads((out / "ranked.json").read_text())["clusters"][0]["key"]
            self.probe(out, key, "#!/bin/sh\nprintf 'still broken\\n' >&2\nexit 1\n")
            patch = self.make_patch(repo, tmp, "int(cmd)")

            result = run(["verify", repo, "--out", out, "--fix", patch])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            record = next(r for r in json.loads((out / "verify.json").read_text())["clusters"]
                          if r["cluster"] == key)
            self.assertEqual(record["status"], "inconclusive")
            self.assertIn("still fails", record["reason"])


if __name__ == "__main__":
    unittest.main()
