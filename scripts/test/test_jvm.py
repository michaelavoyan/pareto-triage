import json
import posixpath
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
from lib.context import extract_sites  # noqa: E402
from lib.entry import extract_entrypoints  # noqa: E402
from lib.imports import build_graph, compute_reach, seeds_from_entrypoints  # noqa: E402
from lib.lang import EXT_LANG, SUPPORTED  # noqa: E402
from lib.walk import walk  # noqa: E402

JAVA = "java-app"
KOTLIN = "kotlin-app"
JAVA_CONTROLLER = "src/main/java/com/acme/api/OrdersController.java"
JAVA_SERVICE = "src/main/java/com/acme/service/OrderService.java"
KOTLIN_ROUTES = "src/main/kotlin/com/acme/api/Routes.kt"


def run(args):
    return subprocess.run([sys.executable, str(CLI)] + [str(a) for a in args],
                          capture_output=True, text=True)


def fixture_files(name):
    return walk(FIXTURES / name)["files"]


def source(rel, text):
    return {"rel": rel, "ext": posixpath.splitext(rel)[1], "text": text}


def context_records(name):
    with tempfile.TemporaryDirectory() as out:
        gate = run(["gate", FIXTURES / name, "--min-loc", "1", "--out", out])
        assert gate.returncode == 0, gate.stdout + gate.stderr
        result = run(["context", FIXTURES / name, "--out", out])
        assert result.returncode == 0, result.stdout + result.stderr
        return [json.loads(line) for line in
                (Path(out) / "context.jsonl").read_text().splitlines() if line.strip()]


class LangTests(unittest.TestCase):
    def test_jvm_extensions_map_to_their_languages(self):
        self.assertEqual(EXT_LANG[".java"], "java")
        self.assertEqual(EXT_LANG[".kt"], "kotlin")
        self.assertEqual(EXT_LANG[".kts"], "kotlin")

    def test_jvm_languages_are_supported(self):
        self.assertLessEqual({"java", "kotlin"}, SUPPORTED)


if __name__ == "__main__":
    unittest.main()
