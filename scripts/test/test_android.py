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
from lib.entry import entrypoint_counts, extract_entrypoints  # noqa: E402
from lib.imports import SEED_BY_KIND, compute_reach, seeds_from_entrypoints  # noqa: E402
from lib.walk import walk  # noqa: E402

ANDROID = "android-app"
JAVA = "app/src/main/java/com/acme/android/"
KOTLIN = "app/src/main/kotlin/com/acme/android/"
JAVA_ACTIVITY = JAVA + "MainActivity.java"
JAVA_STORE = JAVA + "data/OrderStore.java"
JAVA_SERVICE = JAVA + "SyncService.java"
JAVA_RECEIVER = JAVA + "SmsReceiver.java"
JAVA_APPLICATION = JAVA + "AcmeApplication.java"
JAVA_PLAIN = JAVA + "PlainThing.java"
KOTLIN_ACTIVITY = KOTLIN + "FeedActivity.kt"
KOTLIN_WORKER = KOTLIN + "UploadWorker.kt"
KOTLIN_RECEIVER = KOTLIN + "BootReceiver.kt"
KOTLIN_APPLICATION = KOTLIN + "AcmeApp.kt"
KOTLIN_PLAIN = KOTLIN + "PlainFormatter.kt"


def fixture_files(name=ANDROID):
    return walk(FIXTURES / name)["files"]


def source(rel, text):
    return {"rel": rel, "ext": posixpath.splitext(rel)[1], "text": text}


def entries_for(rel, text):
    return extract_entrypoints([source(rel, text)])


def android_entries(rel, text):
    return [e for e in entries_for(rel, text) if e["kind"] in ("ui", "background", "app")]


class FixtureComponentTests(unittest.TestCase):
    """Every Android component in the fixture is seeded by its own base class."""

    def setUp(self):
        self.files = fixture_files()
        self.entries = extract_entrypoints(self.files)
        self.seeds = seeds_from_entrypoints(self.entries)

    def one(self, rel):
        found = [e for e in self.entries if e["file"] == rel]
        self.assertEqual(len(found), 1, (rel, found))
        return found[0]

    def test_java_activity_is_ui_with_seed_five(self):
        entry = self.one(JAVA_ACTIVITY)
        self.assertEqual((entry["kind"], entry["detail"]), ("ui", "ACTIVITY MainActivity"))
        self.assertEqual(self.seeds[JAVA_ACTIVITY], 5)
        self.assertEqual(SEED_BY_KIND["ui"], 5)

    def test_kotlin_activity_is_ui_with_seed_five(self):
        entry = self.one(KOTLIN_ACTIVITY)
        self.assertEqual((entry["kind"], entry["detail"]), ("ui", "ACTIVITY FeedActivity"))
        self.assertEqual(self.seeds[KOTLIN_ACTIVITY], 5)

    def test_java_service_is_background_with_seed_four(self):
        entry = self.one(JAVA_SERVICE)
        self.assertEqual((entry["kind"], entry["detail"]), ("background", "SERVICE SyncService"))
        self.assertEqual(self.seeds[JAVA_SERVICE], 4)
        self.assertEqual(SEED_BY_KIND["background"], 4)

    def test_kotlin_worker_is_background_with_seed_four(self):
        entry = self.one(KOTLIN_WORKER)
        self.assertEqual((entry["kind"], entry["detail"]), ("background", "WORKER UploadWorker"))
        self.assertEqual(self.seeds[KOTLIN_WORKER], 4)

    def test_receivers_are_background(self):
        for rel, name in ((JAVA_RECEIVER, "SmsReceiver"), (KOTLIN_RECEIVER, "BootReceiver")):
            entry = self.one(rel)
            self.assertEqual((entry["kind"], entry["detail"]), ("background", "RECEIVER %s" % name))
            self.assertEqual(self.seeds[rel], 4)

    def test_application_subclasses_are_app_with_seed_three(self):
        for rel, name in ((JAVA_APPLICATION, "AcmeApplication"), (KOTLIN_APPLICATION, "AcmeApp")):
            entry = self.one(rel)
            self.assertEqual((entry["kind"], entry["detail"]), ("app", "APPLICATION %s" % name))
            self.assertEqual(self.seeds[rel], 3)
            self.assertEqual(SEED_BY_KIND["app"], 3)

    def test_plain_classes_are_not_components(self):
        for rel in (JAVA_PLAIN, KOTLIN_PLAIN):
            self.assertEqual([e for e in self.entries if e["file"] == rel], [], rel)
            self.assertNotIn(rel, self.seeds)

    def test_counts_include_the_android_kinds(self):
        counts = entrypoint_counts(self.entries)
        self.assertEqual(counts["ui"], 2)
        self.assertEqual(counts["background"], 4)
        self.assertEqual(counts["app"], 2)
        self.assertEqual(counts["http"], 0)

    def test_imports_from_an_activity_get_reach_four(self):
        reach, _ = compute_reach(self.files, {e["file"] for e in self.entries},
                                 seeds=self.seeds)
        self.assertEqual(reach(JAVA_ACTIVITY), 5)
        self.assertEqual(reach(JAVA_STORE), 4)
        self.assertEqual(reach(JAVA_PLAIN), 1)


class ComponentPatternTests(unittest.TestCase):
    """The base-class list, and nothing looser than it."""

    def test_java_component_bases(self):
        cases = [
            ("Activity", "class A extends Activity {}\n", ("ui", "ACTIVITY A")),
            ("FragmentActivity", "class B extends FragmentActivity {}\n",
             ("ui", "ACTIVITY B")),
            ("ComponentActivity", "class C extends ComponentActivity {}\n",
             ("ui", "ACTIVITY C")),
            ("Fragment", "class D extends Fragment {\n}\n", ("ui", "ACTIVITY D")),
            ("IntentService", "class E extends IntentService {}\n",
             ("background", "SERVICE E")),
            ("JobService", "class F extends JobService {}\n", ("background", "SERVICE F")),
            ("ContentProvider", "class G extends ContentProvider {}\n",
             ("background", "PROVIDER G")),
        ]
        for base, text, expected in cases:
            entries = android_entries("com/acme/%s.java" % base, text)
            self.assertEqual([(e["kind"], e["detail"]) for e in entries], [expected], base)

    def test_qualified_base_names_are_matched(self):
        entries = android_entries(
            "com/acme/Api.java",
            "class Api extends androidx.appcompat.app.AppCompatActivity {}\n")
        self.assertEqual([e["detail"] for e in entries], ["ACTIVITY Api"])

    def test_kotlin_component_bases(self):
        cases = [
            (": FragmentActivity()", ("ui", "ACTIVITY S")),
            (": IntentService(\"sync\")", ("background", "SERVICE S")),
            (": ContentProvider()", ("background", "PROVIDER S")),
            (": Worker(context, params)", ("background", "WORKER S")),
        ]
        for clause, expected in cases:
            entries = android_entries(
                "com/acme/S.kt",
                "class S(val context: Context, val params: Params) %s {\n}\n" % clause)
            self.assertEqual([(e["kind"], e["detail"]) for e in entries], [expected], clause)

    def test_a_wrapped_kotlin_header_still_names_its_base(self):
        entries = android_entries(
            "com/acme/W.kt",
            "class W(\n    private val api: Api,\n    private val cache: Cache,\n"
            ") : Worker(context, params) {\n}\n")
        self.assertEqual([e["detail"] for e in entries], ["WORKER W"])

    def test_a_constructor_parameter_type_is_not_a_base(self):
        entries = android_entries(
            "com/acme/Repo.kt",
            "class Repo(private val service: Service) {\n}\n")
        self.assertEqual(entries, [])

    def test_a_component_name_in_the_body_is_not_a_base(self):
        entries = android_entries(
            "com/acme/Loader.java",
            "public class Loader {\n"
            "    // extends Activity would be a component\n"
            "    void go() {\n    }\n}\n")
        self.assertEqual(entries, [])

    def test_an_android_component_keeps_its_other_entrypoints(self):
        entries = entries_for(
            "com/acme/Api.java",
            "public class Api extends Fragment {\n"
            "    public static void main(String[] args) {\n    }\n}\n")
        self.assertEqual(sorted(e["kind"] for e in entries), ["cli", "ui"])

    def test_android_kinds_reach_the_gate_printout_only_when_non_zero(self):
        with tempfile.TemporaryDirectory() as out:
            result = subprocess.run(
                [sys.executable, str(CLI), "gate", str(FIXTURES / ANDROID),
                 "--min-loc", "1", "--out", out],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            scope = json.loads((Path(out) / "scope.json").read_text())
        self.assertTrue(scope["gate"]["ok"])
        self.assertEqual(scope["entrypoint_kinds"]["ui"], 2)
        line = next(l for l in result.stdout.splitlines() if l.startswith("entries"))
        self.assertIn("2 ui", line)
        self.assertIn("4 background", line)
        self.assertIn("2 app", line)
        self.assertNotIn("http", line)


if __name__ == "__main__":
    unittest.main()
