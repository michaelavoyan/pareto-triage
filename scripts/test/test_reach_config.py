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
from lib.entry import extract_entrypoints  # noqa: E402
from lib.imports import compute_reach, read_aliases, seeds_from_entrypoints  # noqa: E402
from lib.walk import walk  # noqa: E402


def run(args):
    return subprocess.run([sys.executable, str(CLI)] + [str(a) for a in args],
                          capture_output=True, text=True)


def build(root):
    (root / "src").mkdir(parents=True)
    (root / "packages" / "lib" / "src").mkdir(parents=True)
    (root / "tsconfig.json").write_text(
        '{\n  // path aliases\n  "compilerOptions": {"baseUrl": ".", "paths": {"@app/*": ["src/*"]}},\n}\n')
    (root / "package.json").write_text(json.dumps({
        "name": "root", "workspaces": ["packages/*"],
        "dependencies": {"express": "^4"}}))
    (root / "packages" / "lib" / "package.json").write_text(
        json.dumps({"name": "@acme/lib", "version": "1.0.0"}))
    (root / "src" / "routes.ts").write_text(
        "import { db } from '@app/db'\n"
        "import { lib } from '@acme/lib'\n"
        "const app = require('express')()\n"
        "app.get('/x', (req, res) => db(res))\n")
    (root / "src" / "db.ts").write_text("export const db = (x) => x\n")
    (root / "packages" / "lib" / "src" / "index.ts").write_text("export const lib = 1\n")


class AliasTests(unittest.TestCase):
    def test_reads_paths_base_url_and_workspaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build(root)
            aliases = read_aliases(root)
        self.assertEqual(aliases["base_url"], ".")
        self.assertEqual(aliases["paths"], [("@app/*", ["src/*"])])
        self.assertEqual(aliases["packages"], {"@acme/lib": "packages/lib"})

    def test_missing_manifests_are_empty_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(read_aliases(tmp),
                             {"base_url": None, "paths": [], "packages": {}})

    def test_broken_tsconfig_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "tsconfig.json").write_text("{ not json")
            self.assertEqual(read_aliases(tmp)["paths"], [])

    def test_alias_and_workspace_imports_become_reachable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build(root)
            files = walk(root)["files"]
            entries = extract_entrypoints(files)
            seeds = seeds_from_entrypoints(entries)

            plain, _ = compute_reach(files, {e["file"] for e in entries}, seeds=seeds)
            resolved, meta = compute_reach(files, {e["file"] for e in entries},
                                           seeds=seeds, aliases=read_aliases(root))

        self.assertEqual(plain("src/db.ts"), 1)
        self.assertGreater(resolved("src/db.ts"), 1)
        self.assertGreater(resolved("packages/lib/src/index.ts"), 3)
        self.assertEqual(meta["resolved_edges"], 2)

    def test_external_packages_stay_unresolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build(root)
            files = walk(root)["files"]
            entries = extract_entrypoints(files)
            reach, meta = compute_reach(files, {e["file"] for e in entries},
                                        seeds=seeds_from_entrypoints(entries),
                                        aliases=read_aliases(root))
            rels = {f["rel"] for f in files}
        self.assertNotIn("express", rels)
        self.assertEqual(meta["resolved_edges"], 2)


class DepthTests(unittest.TestCase):
    def chain(self, root):
        (root / "src").mkdir(parents=True)
        (root / "src" / "routes.ts").write_text(
            "import './a'\nconst app = require('express')()\napp.get('/x', (q, r) => r)\n")
        (root / "src" / "a.ts").write_text("import './b'\nexport const a = 1\n")
        (root / "src" / "b.ts").write_text("import './c'\nexport const b = 1\n")
        (root / "src" / "c.ts").write_text("export const c = 1\n")

    def test_depth_limits_propagation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.chain(root)
            files = walk(root)["files"]
            entries = extract_entrypoints(files)
            seeds = seeds_from_entrypoints(entries)
            shallow, _ = compute_reach(files, {e["file"] for e in entries}, max_depth=1, seeds=seeds)
            deep, _ = compute_reach(files, {e["file"] for e in entries}, max_depth=3, seeds=seeds)
        self.assertEqual(shallow("src/b.ts"), 1)
        self.assertGreater(deep("src/b.ts"), 1)

    def test_cli_flag_changes_the_recorded_depth(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            self.chain(root)
            out = Path(tmp) / "out"
            run(["gate", root, "--min-loc", "1", "--out", out])
            result = run(["context", root, "--out", out, "--max-depth", "1"])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("depth 1", result.stdout)

    def test_bad_depth_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            self.chain(root)
            out = Path(tmp) / "out"
            run(["gate", root, "--min-loc", "1", "--out", out])
            result = run(["context", root, "--out", out, "--max-depth", "99"])
            self.assertEqual(result.returncode, 2)
            self.assertIn("between 1 and 10", result.stderr)


if __name__ == "__main__":
    unittest.main()
