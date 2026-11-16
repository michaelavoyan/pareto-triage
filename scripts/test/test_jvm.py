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


class JvmImportTests(unittest.TestCase):
    def edges(self, files):
        return build_graph(files)

    def test_java_import_resolves_across_a_maven_source_root(self):
        files = [
            source("src/main/java/com/acme/api/Api.java",
                   "package com.acme.api;\nimport com.acme.svc.Svc;\nclass Api {}\n"),
            source("src/main/java/com/acme/svc/Svc.java",
                   "package com.acme.svc;\nclass Svc {}\n"),
        ]
        self.assertEqual(self.edges(files)["src/main/java/com/acme/api/Api.java"],
                         {"src/main/java/com/acme/svc/Svc.java"})

    def test_java_wildcard_import_names_no_file(self):
        files = [
            source("src/main/java/com/acme/api/Api.java",
                   "package com.acme.api;\nimport com.acme.svc.*;\nclass Api {}\n"),
            source("src/main/java/com/acme/svc/Svc.java",
                   "package com.acme.svc;\nclass Svc {}\n"),
        ]
        self.assertEqual(self.edges(files)["src/main/java/com/acme/api/Api.java"], set())

    def test_java_static_member_import_resolves_to_its_class(self):
        files = [
            source("src/main/java/com/acme/api/Api.java",
                   "package com.acme.api;\nimport static com.acme.util.Text.slug;\nclass Api {}\n"),
            source("src/main/java/com/acme/util/Text.java",
                   "package com.acme.util;\nclass Text { static String slug() { return \"\"; } }\n"),
        ]
        self.assertEqual(self.edges(files)["src/main/java/com/acme/api/Api.java"],
                         {"src/main/java/com/acme/util/Text.java"})

    def test_java_static_import_without_a_scanned_class_stays_unresolved(self):
        files = [
            source("src/main/java/com/acme/api/Api.java",
                   "package com.acme.api;\nimport static com.acme.util.Text.slug;\nclass Api {}\n"),
        ]
        self.assertEqual(self.edges(files)["src/main/java/com/acme/api/Api.java"], set())

    def test_java_same_package_access_needs_the_type_name(self):
        files = [
            source("src/main/java/com/acme/svc/A.java",
                   "package com.acme.svc;\nclass A { void go() { new Used(); } }\n"),
            source("src/main/java/com/acme/svc/Used.java",
                   "package com.acme.svc;\nclass Used {}\n"),
            source("src/main/java/com/acme/svc/Unused.java",
                   "package com.acme.svc;\nclass Unused {}\n"),
        ]
        self.assertEqual(self.edges(files)["src/main/java/com/acme/svc/A.java"],
                         {"src/main/java/com/acme/svc/Used.java"})

    def test_java_same_package_does_not_cross_directories(self):
        files = [
            source("src/main/java/com/acme/svc/A.java",
                   "package com.acme.svc;\nclass A { void go() { new Used(); } }\n"),
            source("src/main/java/com/acme/other/Used.java",
                   "package com.acme.other;\nclass Used {}\n"),
        ]
        self.assertEqual(self.edges(files)["src/main/java/com/acme/svc/A.java"], set())

    def test_java_package_declaration_that_disagrees_with_the_directory_is_not_guessed(self):
        files = [
            source("src/main/java/com/acme/api/Api.java",
                   "package com.acme.api;\nimport com.acme.foo.Bar;\nclass Api {}\n"),
            source("weird/dir/Bar.java", "package com.acme.foo;\nclass Bar {}\n"),
        ]
        self.assertEqual(self.edges(files)["src/main/java/com/acme/api/Api.java"], set())

    def test_duplicate_package_paths_pick_the_shallower_file_every_time(self):
        files = [
            source("src/main/java/com/acme/api/Api.java",
                   "package com.acme.api;\nimport com.acme.Foo;\nclass Api {}\n"),
            source("a/com/acme/Foo.java", "package com.acme;\nclass Foo {}\n"),
            source("com/acme/Foo.java", "package com.acme;\nclass Foo {}\n"),
        ]
        first = self.edges(files)["src/main/java/com/acme/api/Api.java"]
        second = self.edges(files)["src/main/java/com/acme/api/Api.java"]
        self.assertEqual(first, {"com/acme/Foo.java"})
        self.assertEqual(first, second)

    def test_kotlin_import_tries_class_file_lowercase_and_java(self):
        files = [
            source("src/main/kotlin/com/acme/app/App.kt",
                   "package com.acme.app\n"
                   "import com.acme.svc.Service\n"
                   "import com.acme.svc.helper\n"
                   "import com.acme.legacy.Store\n"
                   "fun main() {}\n"),
            source("src/main/kotlin/com/acme/svc/Service.kt", "package com.acme.svc\nclass Service\n"),
            source("src/main/kotlin/com/acme/svc/helper.kt", "package com.acme.svc\nfun helper() = 1\n"),
            source("src/main/java/com/acme/legacy/Store.java",
                   "package com.acme.legacy;\npublic class Store {}\n"),
        ]
        self.assertEqual(self.edges(files)["src/main/kotlin/com/acme/app/App.kt"], {
            "src/main/kotlin/com/acme/svc/Service.kt",
            "src/main/kotlin/com/acme/svc/helper.kt",
            "src/main/java/com/acme/legacy/Store.java",
        })

    def test_kotlin_star_import_names_no_file(self):
        files = [
            source("src/main/kotlin/com/acme/app/App.kt",
                   "package com.acme.app\nimport com.acme.svc.*\nfun main() {}\n"),
            source("src/main/kotlin/com/acme/svc/Service.kt", "package com.acme.svc\nclass Service\n"),
        ]
        self.assertEqual(self.edges(files)["src/main/kotlin/com/acme/app/App.kt"], set())

    def test_kotlin_has_no_same_package_edges(self):
        files = [
            source("com/acme/a/One.kt", "package com.acme.a\nclass One { fun go() = Two() }\n"),
            source("com/acme/a/Two.kt", "package com.acme.a\nclass Two\n"),
        ]
        self.assertEqual(self.edges(files)["com/acme/a/One.kt"], set())

    def test_external_imports_stay_unresolved(self):
        files = [
            source("src/main/java/com/acme/Api.java",
                   "package com.acme;\n"
                   "import com.missing.Thing;\n"
                   "import com.missing.util.*;\n"
                   "class Api {}\n"),
            source("src/main/kotlin/com/acme/App.kt",
                   "package com.acme\n"
                   "import org.springframework.web.bind.annotation.GetMapping\n"
                   "fun main() {}\n"),
        ]
        graph = self.edges(files)
        self.assertEqual(set(graph), {f["rel"] for f in files})
        for targets in graph.values():
            self.assertEqual(targets, set())


class JvmEntryTests(unittest.TestCase):
    def entries(self, rel, text):
        return extract_entrypoints([source(rel, text)])

    def test_entry_annotations_are_http_entrypoints(self):
        entries = self.entries("com/acme/Api.java",
                               "class Api {\n"
                               "    @GetMapping(\"/orders\")\n"
                               "    String list() { return \"\"; }\n"
                               "    @PostMapping(\"/orders\")\n"
                               "    String create() { return \"\"; }\n"
                               "}\n")
        self.assertEqual(sorted(e["detail"] for e in entries if e["kind"] == "http"),
                         ["GET /orders", "POST /orders"])
        self.assertTrue(all(e["framework"] == "spring" for e in entries if e["kind"] == "http"))

    def test_request_mapping_without_a_verb_is_any(self):
        entries = self.entries("com/acme/Api.java",
                               "@RequestMapping(\"/x\")\nclass Api {\n}\n")
        self.assertEqual([e["detail"] for e in entries], ["ANY /x"])

    def test_request_mapping_method_attribute_names_the_verb(self):
        entries = self.entries("com/acme/Api.java",
                               "@RequestMapping(value = \"/y\", method = RequestMethod.POST)\n"
                               "class Api {\n}\n")
        self.assertEqual([e["detail"] for e in entries], ["POST /y"])

    def test_jaxrs_get_and_post_are_http(self):
        entries = self.entries("com/acme/Resource.java",
                               "@Path(\"/r\")\nclass Resource {\n"
                               "    @GET\n    public String get() { return \"\"; }\n"
                               "    @POST\n    public String post() { return \"\"; }\n"
                               "}\n")
        self.assertEqual(sorted(e["detail"] for e in entries if e["kind"] == "http"),
                         ["GET", "POST"])
        self.assertTrue(all(e["framework"] == "jaxrs" for e in entries if e["kind"] == "http"))

    def test_java_and_kotlin_main_are_cli_entrypoints(self):
        java = self.entries("com/acme/App.java",
                            "public class App {\n"
                            "    public static void main(String[] args) {\n    }\n}\n")
        self.assertEqual([(e["kind"], e["detail"], e["framework"]) for e in java],
                         [("cli", "main", "java")])
        kotlin = self.entries("com/acme/App.kt",
                              "fun main(args: Array<String>) {\n}\n")
        self.assertEqual([(e["kind"], e["detail"], e["framework"]) for e in kotlin],
                         [("cli", "main", "kotlin")])

    def test_comment_annotation_is_not_special_cased(self):
        entries = self.entries("com/acme/Notes.java",
                               "// @GetMapping(\"/ghost\") is documentation, not a route\n"
                               "public class Notes {\n}\n")
        self.assertEqual([e["detail"] for e in entries], ["GET /ghost"])


class JvmFixtureTests(unittest.TestCase):
    def test_gate_accepts_both_fixtures(self):
        for name in (JAVA, KOTLIN):
            with tempfile.TemporaryDirectory() as out:
                result = run(["gate", FIXTURES / name, "--min-loc", "1", "--out", out])
                self.assertEqual(result.returncode, 0, name + result.stdout + result.stderr)
                scope = json.loads((Path(out) / "scope.json").read_text())
            self.assertTrue(scope["gate"]["ok"], name)
            supported = {entry["lang"] for entry in scope["size"]["by_language"]}
            self.assertIn("java" if name == JAVA else "kotlin", supported)

    def test_entry_annotations_are_http_entrypoints_in_the_fixtures(self):
        entries = extract_entrypoints(fixture_files(JAVA))
        self.assertEqual(sorted(e["detail"] for e in entries if e["kind"] == "http"),
                         ["GET /orders", "POST /orders"])
        self.assertEqual([e["detail"] for e in entries if e["kind"] == "cli"], ["main"])

        entries = extract_entrypoints(fixture_files(KOTLIN))
        self.assertEqual(sorted(e["detail"] for e in entries if e["kind"] == "http"),
                         ["GET /greet", "POST /greet"])

    def test_java_imported_file_is_reachable_and_entry_file_scores_five(self):
        files = fixture_files(JAVA)
        entries = extract_entrypoints(files)
        reach, _ = compute_reach(files, {e["file"] for e in entries},
                                 seeds=seeds_from_entrypoints(entries))
        self.assertEqual(reach(JAVA_CONTROLLER), 5)
        self.assertGreater(reach(JAVA_SERVICE), 1)
        self.assertEqual(reach(JAVA_SERVICE), 4)

    def test_unresolved_external_imports_are_not_edges(self):
        files = fixture_files(JAVA)
        known = {f["rel"] for f in files}
        graph = build_graph(files)
        for rel, targets in graph.items():
            self.assertLessEqual(targets, known, rel)
        self.assertEqual(graph[JAVA_CONTROLLER], {JAVA_SERVICE})

    def test_java_same_package_edge_in_the_fixture_requires_use(self):
        graph = build_graph(fixture_files(JAVA))
        pricing = "src/main/java/com/acme/service/PricingService.java"
        self.assertIn(pricing, graph[JAVA_SERVICE])          # used in a field
        self.assertNotIn(JAVA_SERVICE, graph[pricing])       # visible, never named

    def test_kotlin_lowercase_and_java_imports_are_reachable(self):
        files = fixture_files(KOTLIN)
        entries = extract_entrypoints(files)
        reach, _ = compute_reach(files, {e["file"] for e in entries},
                                 seeds=seeds_from_entrypoints(entries))
        self.assertEqual(reach(KOTLIN_ROUTES), 5)
        self.assertEqual(reach("src/main/kotlin/com/acme/service/clock.kt"), 4)
        self.assertEqual(reach("src/main/java/com/acme/legacy/LegacyStore.java"), 4)


if __name__ == "__main__":
    unittest.main()
