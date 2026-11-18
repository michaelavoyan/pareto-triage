"""Candidate-site bounds for Swift and Objective-C.

The unit cases are the shapes that broke the first extractor: interpolation and
raw strings whose braces are not structural, and Objective-C methods whose
signature or body holds a block. The fixture cases run the same code over a
tree.
"""

import json
import posixpath
import re
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
from lib.context import LANG_BY_EXT, extract_sites  # noqa: E402
from lib.walk import walk  # noqa: E402

IOS = "ios-app"
SHAPES = "Signal/SiteShapes.swift"
LEGACY_STORE = "Signal/ObjC/LegacyStore.m"
ACCOUNTS = "Signal/ObjC/AccountsViewController.m"


def run(args):
    return subprocess.run([sys.executable, str(CLI)] + [str(a) for a in args],
                          capture_output=True, text=True)


def fixture_files(name):
    return walk(FIXTURES / name)["files"]


def source(rel, text):
    return {"rel": rel, "ext": posixpath.splitext(rel)[1], "text": text}


def sites_for(rel, text):
    sites, _ = extract_sites([source(rel, text)], lambda rel: 5)
    return sites


def one(sites, name):
    return next(site for site in sites if site["function"] == name)


DECLARATION_RE = re.compile(
    r"\b(?:func|init|deinit|class|struct|enum|extension|protocol|actor)\b|^[+-] \([^)]*\)")


def starts_on_a_declaration(site):
    first = site["source"].splitlines()[0].strip()
    return first.startswith(("@", "var ", "let ")) or bool(DECLARATION_RE.search(first))


class LangDispatchTests(unittest.TestCase):
    def test_swift_and_objc_extensions_map_to_their_languages(self):
        self.assertEqual(LANG_BY_EXT[".swift"], "swift")
        self.assertEqual(LANG_BY_EXT[".m"], "objc")
        self.assertEqual(LANG_BY_EXT[".mm"], "objc")

    def test_a_swift_file_is_not_parsed_as_a_jvm_or_js_file(self):
        text = "final class Api {\n    func one() -> Int {\n        return 1\n    }\n}\n"
        sites = sites_for("App/Api.swift", text)
        self.assertEqual([(s["function"], s["lang"]) for s in sites], [("one", "swift")])


class SwiftSiteTests(unittest.TestCase):
    def test_interpolation_with_braces_keeps_the_declaration_bounds(self):
        text = ("final class Formatter {\n"
                "    func render(_ a: String, _ b: String) -> String {\n"
                "        let text = \"\\(a) {\\(b)}\"\n"
                "        return text\n"
                "    }\n"
                "\n"
                "    func after() -> Int {\n"
                "        1\n"
                "    }\n"
                "}\n")
        sites = sites_for("App/Formatter.swift", text)
        render = one(sites, "render")
        self.assertEqual(render["lines"], [2, 5])
        self.assertTrue(render["source"].splitlines()[0].lstrip().startswith("func render("))
        self.assertEqual(render["source"].splitlines()[-1].strip(), "}")
        self.assertEqual(one(sites, "after")["lines"], [7, 9])

    def test_nested_strings_inside_interpolation_keep_the_bounds(self):
        text = ("func render(_ name: String) -> String {\n"
                "    let text = \"\\(name.isEmpty ? \"(\\(name))\" : \"{\")}\"\n"
                "    return text\n"
                "}\n")
        site = sites_for("App/Render.swift", text)[0]
        self.assertEqual(site["lines"], [1, 4])

    def test_raw_string_with_braces_keeps_the_declaration_bounds(self):
        text = ("func json() -> String {\n"
                "    let one = #\"{\"a\": {\"b\": 1}}\"#\n"
                "    let two = ##\"{\"a\": {\"b\": #1}}\"##\n"
                "    return one + two\n"
                "}\n")
        site = sites_for("App/Json.swift", text)[0]
        self.assertEqual(site["lines"], [1, 5])
        self.assertTrue(site["source"].splitlines()[0].startswith("func json("))
        self.assertEqual(site["source"].splitlines()[-1].strip(), "}")

    def test_multiline_string_with_braces_keeps_the_declaration_bounds(self):
        text = ("func template() -> String {\n"
                "    return \"\"\"\n"
                "    {\n"
                "      \"a\": 1\n"
                "    }\n"
                "    \"\"\"\n"
                "}\n")
        site = sites_for("App/Template.swift", text)[0]
        self.assertEqual(site["lines"], [1, 7])

    def test_computed_property_with_a_body_is_a_site_and_stored_properties_are_not(self):
        text = ("final class Holder {\n"
                "    var stored: Int = 0\n"
                "    var declared: String\n"
                "    var computed: Int {\n"
                "        stored + 1\n"
                "    }\n"
                "}\n")
        sites = sites_for("App/Holder.swift", text)
        self.assertEqual([(s["function"], s["lines"]) for s in sites], [("computed", [4, 6])])
        self.assertEqual(sites[0]["enclosed_by"], ["Holder"])

    def test_a_local_variable_is_not_a_site_and_does_not_displace_its_function(self):
        text = ("func validate(_ url: URL) -> Bool {\n"
                "    let host: String?\n"
                "    var resolved: String?\n"
                "    if url.host != nil {\n"
                "        host = url.host\n"
                "        resolved = url.host\n"
                "    } else {\n"
                "        return false\n"
                "    }\n"
                "    return host == resolved\n"
                "}\n")
        sites = sites_for("App/Validate.swift", text)
        self.assertEqual([(s["function"], s["lines"]) for s in sites],
                         [("validate", [1, 11])])

    def test_a_protocol_property_requirement_is_not_a_site(self):
        text = ("protocol Named {\n"
                "    var name: String { get }\n"
                "}\n")
        sites = sites_for("App/Named.swift", text)
        self.assertEqual([s["function"] for s in sites], ["Named"])

    def test_deinit_is_a_site(self):
        text = ("final class Session {\n"
                "    deinit {\n"
                "        clean()\n"
                "    }\n"
                "}\n")
        site = sites_for("App/Session.swift", text)[0]
        self.assertEqual((site["function"], site["lines"]), ("deinit", [2, 4]))

    def test_a_plain_struct_with_a_function_yields_the_function(self):
        text = ("struct Model {\n"
                "    func describe() -> String {\n"
                "        \"m\"\n"
                "    }\n"
                "}\n")
        sites = sites_for("App/Model.swift", text)
        self.assertEqual([(s["function"], s["lines"]) for s in sites], [("describe", [2, 4])])
        self.assertEqual(sites[0]["enclosed_by"], ["Model"])

    def test_class_with_methods_yields_only_the_methods(self):
        text = ("final class Api {\n"
                "    func one() -> Int {\n"
                "        return 1\n"
                "    }\n"
                "}\n")
        sites = sites_for("App/Api.swift", text)
        self.assertEqual([s["function"] for s in sites], ["one"])
        self.assertEqual(sites[0]["enclosed_by"], ["Api"])

    def test_class_with_no_methods_is_the_site(self):
        text = ("final class Empty {\n"
                "    let id: String = \"\"\n"
                "}\n")
        sites = sites_for("App/Empty.swift", text)
        self.assertEqual([(s["function"], s["lines"]) for s in sites], [("Empty", [1, 3])])

    def test_attribute_lines_are_included_in_the_bounds(self):
        text = ("final class Worker {\n"
                "    @MainActor\n"
                "    @discardableResult\n"
                "    @objc\n"
                "    func run() -> Bool {\n"
                "        true\n"
                "    }\n"
                "}\n")
        site = one(sites_for("App/Worker.swift", text), "run")
        self.assertEqual(site["lines"], [2, 7])
        self.assertEqual(site["source"].splitlines()[0].strip(), "@MainActor")
        self.assertEqual(site["source"].splitlines()[-1].strip(), "}")

    def test_a_single_line_expression_body_is_not_a_site_and_a_wrapped_one_is(self):
        text = ("func single() -> Int = 1\n"
                "func wrapped() -> [Int] = [\n"
                "    1,\n"
                "    2,\n"
                "]\n"
                "func after() -> Int {\n"
                "    2\n"
                "}\n")
        bounds = {s["function"]: s["lines"] for s in sites_for("App/Expr.swift", text)}
        self.assertNotIn("single", bounds)
        self.assertEqual(bounds["wrapped"], [2, 5])
        self.assertEqual(bounds["after"], [6, 8])

    def test_an_init_is_a_site_with_its_attribute_lines(self):
        text = ("final class Cache {\n"
                "    @inlinable\n"
                "    init(size: Int) {\n"
                "        self.size = size\n"
                "    }\n"
                "}\n")
        site = one(sites_for("App/Cache.swift", text), "init")
        self.assertEqual(site["lines"], [2, 5])


class ObjcSiteTests(unittest.TestCase):
    def test_block_argument_with_braces_ends_at_the_method_brace(self):
        text = ("@implementation Runner\n"
                "\n"
                "- (void)runWithCompletion:(void (^)(BOOL ok))completion {\n"
                "    void (^local)(void) = ^{\n"
                "        if (YES) { NSLog(@\"{ not a brace }\"); }\n"
                "    };\n"
                "    completion(YES);\n"
                "}\n"
                "\n"
                "- (void)after {\n"
                "}\n"
                "@end\n")
        sites = sites_for("App/Runner.m", text)
        run_site = one(sites, "runWithCompletion")
        self.assertEqual(run_site["lines"], [3, 8])
        self.assertEqual(run_site["source"].splitlines()[-1].strip(), "}")
        self.assertIn("};", run_site["source"])
        self.assertEqual(one(sites, "after")["lines"], [10, 11])

    def test_a_multiline_signature_is_one_site(self):
        text = ("@implementation Sender\n"
                "\n"
                "- (void)sendMessage:(NSString *)text\n"
                "              toUser:(User *)user\n"
                "          completion:(void (^)(BOOL ok))completion\n"
                "{\n"
                "    completion(YES);\n"
                "}\n"
                "\n"
                "- (NSInteger)count {\n"
                "    return 0;\n"
                "}\n"
                "@end\n")
        sites = sites_for("App/Sender.m", text)
        send = one(sites, "sendMessage")
        self.assertEqual(send["lines"], [3, 8])
        self.assertTrue(send["source"].splitlines()[0].startswith("- (void)sendMessage:"))
        self.assertEqual(one(sites, "count")["lines"], [10, 12])

    def test_an_implementation_is_a_container_not_a_site(self):
        text = ("@implementation Runner\n"
                "- (void)run {\n"
                "}\n"
                "@end\n")
        sites = sites_for("App/Runner.m", text)
        self.assertEqual([s["function"] for s in sites], ["run"])
        self.assertEqual(sites[0]["enclosed_by"], ["Runner"])

    def test_a_declaration_without_a_body_is_not_a_site(self):
        text = ("@implementation Talker\n"
                "- (void)say;\n"
                "\n"
                "- (void)doSay {\n"
                "}\n"
                "@end\n")
        sites = sites_for("App/Talker.m", text)
        self.assertEqual([(s["function"], s["lines"]) for s in sites], [("doSay", [4, 5])])

    def test_a_mm_file_is_objc(self):
        text = ("@implementation Metric\n"
                "+ (instancetype)sharedMetric {\n"
                "    return nil;\n"
                "}\n"
                "@end\n")
        sites = sites_for("App/Metric.mm", text)
        self.assertEqual([(s["function"], s["lang"]) for s in sites],
                         [("sharedMetric", "objc")])


class FixtureSiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = fixture_files(IOS)
        cls.sites, _ = extract_sites(cls.files, lambda rel: 5)
        cls.by_file = {}
        for site in cls.sites:
            cls.by_file.setdefault(site["file"], []).append(site)

    def test_the_swift_fixture_yields_every_declaration_shape(self):
        names = {site["function"] for site in self.by_file[SHAPES]}
        self.assertEqual(names, {"init", "deinit", "summary", "render", "wrapped"})
        for site in self.by_file[SHAPES]:
            self.assertEqual(site["lang"], "swift")
            self.assertEqual(site["enclosed_by"], ["SiteShapes"])

    def test_the_objc_fixture_yields_its_methods(self):
        names = {site["function"]: site["lines"] for site in self.by_file[LEGACY_STORE]}
        self.assertEqual(sorted(names), ["sharedStore", "store"])
        store = next(s for s in self.by_file[LEGACY_STORE] if s["function"] == "store")
        self.assertEqual(store["lines"], [5, 13])
        self.assertEqual(store["lang"], "objc")
        self.assertEqual(store["enclosed_by"], ["LegacyStore"])

    def test_fixture_sources_start_on_a_declaration_line(self):
        for site in self.sites:
            self.assertTrue(starts_on_a_declaration(site),
                            (site["file"], site["source"].splitlines()[0]))

    def test_context_writes_swift_and_objc_records(self):
        with tempfile.TemporaryDirectory() as out:
            gate = run(["gate", FIXTURES / IOS, "--min-loc", "1", "--out", out])
            self.assertEqual(gate.returncode, 0, gate.stdout + gate.stderr)
            result = run(["context", FIXTURES / IOS, "--out", out])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            records = [json.loads(line) for line in
                       (Path(out) / "context.jsonl").read_text().splitlines() if line.strip()]

        langs = {record["lang"] for record in records}
        self.assertEqual(langs, {"swift", "objc"})
        for record in records:
            self.assertTrue(starts_on_a_declaration(record),
                            (record["file"], record["source"].splitlines()[0]))


if __name__ == "__main__":
    unittest.main()
