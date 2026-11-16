import json
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

sys.path.insert(0, str(SCRIPTS))
from lib.verify import make_worktree, remove_worktree  # noqa: E402


def run(args):
    return subprocess.run([sys.executable, str(CLI)] + [str(a) for a in args],
                          capture_output=True, text=True)


class CopyIsolationTests(unittest.TestCase):
    def test_plain_directory_is_copied_without_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            (repo / "src").mkdir(parents=True)
            (repo / "src" / "a.py").write_text("x = 1\n")
            (repo / "out").mkdir()
            (repo / "out" / "junk.json").write_text("{}")
            worktree, info = make_worktree(repo)
            try:
                self.assertEqual(info["isolation"], "copy")
                self.assertTrue((worktree / "src" / "a.py").exists())
                self.assertFalse((worktree / "out").exists())
                self.assertFalse((worktree / ".git").exists())
            finally:
                remove_worktree(repo, worktree, info)

    def test_probe_writes_never_touch_the_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            (repo / "src").mkdir(parents=True)
            (repo / "src" / "app.py").write_text(
                "import subprocess\n\n\ndef run(c):\n    return eval(c)\n\n\n"
                "if __name__ == '__main__':\n    run('1')\n")
            out = Path(tmp) / "out"
            for command in (["gate", repo, "--min-loc", "1", "--out", out],
                            ["context", repo, "--out", out],
                            ["detect", repo, "--out", out],
                            ["rank", repo, "--out", out]):
                result = run(command)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            key = json.loads((out / "ranked.json").read_text())["clusters"][0]["key"]
            probes = out / "probes"
            probes.mkdir()
            (probes / (key + ".sh")).write_text(
                "#!/bin/sh\necho touched > side-effect.txt\nexit 1\n")

            result = run(["verify", repo, "--out", out])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads((out / "verify.json").read_text())
            self.assertEqual(payload["isolation"], "copy")
            self.assertIn("copied tree", payload["mode"])
            self.assertFalse((repo / "side-effect.txt").exists())


if __name__ == "__main__":
    unittest.main()
