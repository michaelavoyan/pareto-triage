"""Swift and Objective-C: recognition, import resolution, target membership."""

import json
import posixpath
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
from lib import xcode  # noqa: E402
from lib.entry import extract_entrypoints, entrypoint_counts  # noqa: E402
from lib.imports import (SEED_BY_KIND, build_graph, compute_reach,  # noqa: E402
                         seeds_from_entrypoints)
from lib.lang import EXT_LANG, SUPPORTED, SUPPORTED_LABEL  # noqa: E402
from lib.walk import count_loc, walk  # noqa: E402

SWIFT = "swift-app"
OBJC = "objc-app"
IOS = "ios-app"
PBXPROJ = "App.xcodeproj/project.pbxproj"
APP_MAIN = "App/AppMain.swift"
HELPERS = "App/Helpers.swift"
UNUSED = "App/Unused.swift"
IMPORTER = "App/ModuleImporter.swift"
ORPHAN = "App/Orphan.swift"
CORE_STORE = "Core/CoreStore.swift"
ACCOUNT_M = "Signal/Account.m"
ACCOUNT_H = "Signal/Account.h"
CATEGORY_M = "Signal/Account+Formatting.m"
ORDER_STORE_M = "Signal/Orders/OrderStore.m"
METRIC_MM = "Signal/Legacy/Metric.mm"


def run(args):
    return subprocess.run([sys.executable, str(CLI)] + [str(a) for a in args],
                          capture_output=True, text=True)


def fixture_files(name):
    return walk(FIXTURES / name)["files"]


def source(rel, text):
    return {"rel": rel, "ext": posixpath.splitext(rel)[1], "text": text}


class LangTests(unittest.TestCase):
    def test_swift_and_objc_extensions_map_to_their_languages(self):
        self.assertEqual(EXT_LANG[".swift"], "swift")
        self.assertEqual(EXT_LANG[".m"], "objc")
        self.assertEqual(EXT_LANG[".mm"], "objc")

    def test_swift_and_objc_are_supported(self):
        self.assertLessEqual({"swift", "objc"}, SUPPORTED)
        self.assertIn("objc", SUPPORTED_LABEL)
        self.assertIn("swift", SUPPORTED_LABEL)

    def test_headers_are_not_sources(self):
        self.assertNotIn(".h", EXT_LANG)

    def test_refusal_message_lists_the_supported_languages_it_ships_with(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            (repo / "main.go").write_text("package main\n\nfunc main() {}\n")
            out = Path(tmp) / "out"
            result = run(["gate", repo, "--out", out])
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            reasons = json.loads((out / "scope.json").read_text())["gate"]["reasons"]
            message = next(r for r in reasons if "supports" in r)
            self.assertIn(SUPPORTED_LABEL, message)
            self.assertIn("swift", message)
            self.assertIn("objc", message)


class ObjcImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = fixture_files(OBJC)
        cls.graph = build_graph(cls.files)

    def test_angle_import_resolves_to_the_implementation(self):
        self.assertEqual(self.graph[ORDER_STORE_M], {ACCOUNT_M})

    def test_a_category_resolves_the_class_it_extends(self):
        self.assertEqual(self.graph[CATEGORY_M], {ACCOUNT_M})

    def test_an_implementation_importing_its_own_header_has_no_self_edge(self):
        self.assertEqual(self.graph[ACCOUNT_M], set())
        self.assertEqual(self.graph[METRIC_MM], set())

    def test_headers_are_not_graph_nodes(self):
        for rel in self.graph:
            self.assertFalse(rel.endswith(".h"), rel)

    def test_an_import_of_an_unscanned_header_stays_unresolved(self):
        files = [
            source("Signal/A.m", '#import "Missing.h"\n#import <UIKit/UIKit.h>\n'),
        ]
        self.assertEqual(build_graph(files)["Signal/A.m"], set())

    def test_duplicate_basenames_from_another_directory_stay_unresolved(self):
        files = [
            source("Other/Uses.m", '#import "Shared.h"\n'),
            source("App/Shared.h", "@interface Shared : NSObject\n@end\n"),
            source("App/Shared.m", '#import "Shared.h"\n'),
            source("App/Deep/Nest/Shared.h", "@interface Shared : NSObject\n@end\n"),
            source("App/Deep/Nest/Shared.m", '#import "Shared.h"\n'),
        ]
        meta = {}
        graph = build_graph(files, meta=meta)
        self.assertEqual(graph["Other/Uses.m"], set())
        self.assertEqual(meta["objc"]["ambiguous"], 1)
        self.assertEqual(build_graph(files)["Other/Uses.m"], set())

    def test_a_directory_path_that_does_not_match_still_takes_a_unique_basename(self):
        hits = build_graph(self.files)["Signal/Orders/Recent.m"]
        self.assertEqual(hits, {"Signal/Legacy/Dates.m"})

    def test_basename_fallbacks_and_ambiguity_are_counted_in_reach_meta(self):
        meta = {}
        build_graph(self.files, meta=meta)
        self.assertEqual(meta["objc"]["basename_fallbacks"], 1)
        self.assertEqual(meta["objc"]["ambiguous"], 1)

    def test_a_unique_basename_with_no_implementation_resolves_to_the_header(self):
        files = [
            source("App/Uses.m", '#import "Only/Declared.h"\n'),
            source("App/Declared.h", "@interface Declared : NSObject\n@end\n"),
        ]
        meta = {}
        build_graph(files, meta=meta)
        self.assertEqual(meta["objc"]["resolved"], 1)
        self.assertEqual(meta["objc"]["basename_fallbacks"], 1)

    def test_relative_import_is_normalised_from_the_importing_directory(self):
        files = [
            source("App/Orders/Store.m", '#import "../Account.h"\n'),
            source("App/Account.h", "@interface Account : NSObject\n@end\n"),
            source("App/Account.m", '#import "Account.h"\n'),
        ]
        self.assertEqual(build_graph(files)["App/Orders/Store.m"], {"App/Account.m"})

    def test_header_lines_are_never_counted_as_supported_code(self):
        with tempfile.TemporaryDirectory() as out:
            result = run(["gate", FIXTURES / OBJC, "--min-loc", "1", "--out", out])
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            scope = json.loads((Path(out) / "scope.json").read_text())
        by_lang = {entry["lang"]: entry for entry in scope["size"]["by_language"]}
        self.assertEqual(list(by_lang), ["objc"])
        implemented = [f for f in self.files if f["ext"] in (".m", ".mm")]
        self.assertEqual(by_lang["objc"]["files"], len(implemented))
        self.assertEqual(by_lang["objc"]["loc"],
                         sum(count_loc(f["text"]) for f in implemented))
        self.assertGreater(scope["size"]["total_loc"], by_lang["objc"]["loc"])
        self.assertNotIn("c", scope["languages"]["supported"])


class SwiftTargetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = fixture_files(SWIFT)
        cls.meta = {}
        cls.graph = build_graph(cls.files, meta=cls.meta)
        cls.membership = xcode.membership(cls.files)

    def test_the_project_file_gives_each_file_a_target(self):
        self.assertEqual(self.membership["pbxproj"], [PBXPROJ])
        self.assertEqual(self.membership["targets"], {
            "App": [APP_MAIN, HELPERS, IMPORTER, UNUSED],
            "Core": [CORE_STORE],
        })

    def test_a_swift_file_outside_every_target_has_no_target(self):
        mapped = {rel for rels in self.membership["targets"].values() for rel in rels}
        self.assertNotIn(ORPHAN, mapped)

    def test_a_type_mention_in_the_same_target_is_an_edge(self):
        self.assertEqual(self.graph[APP_MAIN], {HELPERS})

    def test_the_same_type_mentioned_across_targets_is_not_an_edge(self):
        self.assertNotIn(CORE_STORE, self.graph[APP_MAIN])

    def test_a_declared_type_that_is_not_mentioned_is_not_an_edge(self):
        self.assertNotIn(UNUSED, self.graph[APP_MAIN])

    def test_an_unmapped_file_gets_no_edges(self):
        self.assertEqual(self.graph[ORPHAN], set())

    def test_a_module_import_creates_no_edge(self):
        self.assertEqual(self.graph[IMPORTER], set())

    def test_an_import_of_a_module_that_is_not_a_target_is_ignored(self):
        files = [
            source("App/Foo.swift", "import Foundation\nimport UIKit\nstruct Foo {}\n"),
        ]
        self.assertEqual(build_graph(files)["App/Foo.swift"], set())

    def test_a_commented_module_import_is_ignored(self):
        files = ([f for f in self.files if f["rel"] != IMPORTER]
                 + [source(IMPORTER, "// import Core\nfinal class ModuleImporter {}\n")])
        self.assertEqual(build_graph(files)[IMPORTER], set())

    def test_a_comment_mention_is_not_a_mention(self):
        files = [
            source("App/A.swift", "struct A {}\n"),
            source("App/B.swift", "// struct A is the one we use\nstruct B {}\n"),
        ]
        self.assertEqual(build_graph(files)["App/B.swift"], set())

    def test_class_func_is_not_a_type_declaration(self):
        from lib.imports import _swift_declarations
        text = ("final class Store {\n"
                "    class func shared() -> Store { Store() }\n"
                "    class var empty: [String] { [] }\n"
                "}\n")
        self.assertEqual(_swift_declarations(text), ["Store"])

    def test_project_paths_are_matched_by_trailing_segments(self):
        files = [
            source("Signal/App/Foo.swift", "struct Foo {}\n"),
            source("Signal/App/Bar.swift", "struct Bar { let foo = Foo() }\n"),
            source("Signal/Signal.xcodeproj/project.pbxproj", PROJECT),
        ]
        self.assertEqual(build_graph(files)["Signal/App/Bar.swift"], {"Signal/App/Foo.swift"})

    def test_reach_meta_reports_what_the_project_gave(self):
        swift = self.meta["swift"]
        self.assertEqual(swift["pbxproj"], [PBXPROJ])
        self.assertEqual(swift["targets"], ["App", "Core"])
        self.assertEqual(swift["swift_files"], 6)
        self.assertEqual(swift["mapped_files"], 5)
        self.assertEqual(swift["mention_edges"], 1)
        self.assertEqual(swift["module_edges"], 0)
        self.assertEqual(swift["module_edge_rule"], "dropped")
        self.assertIsNone(swift["note"])

    def test_without_a_project_file_the_graph_says_so_instead_of_guessing(self):
        files = [
            source("App/A.swift", "struct A {}\n"),
            source("App/B.swift", "struct B { let a = A() }\n"),
        ]
        meta = {}
        graph = build_graph(files, meta=meta)
        self.assertEqual(graph["App/B.swift"], set())
        self.assertEqual(meta["swift"]["pbxproj"], [])
        self.assertEqual(meta["swift"]["mapped_files"], 0)
        self.assertIn("no project.pbxproj", meta["swift"]["note"])

    def test_reach_meta_from_compute_reach_carries_the_swift_section(self):
        reach, meta = compute_reach(self.files, [], seeds={IMPORTER: 5}, max_depth=3)
        self.assertEqual(reach(CORE_STORE), 1)  # a module import is not an edge
        self.assertEqual(reach(ORPHAN), 1)
        self.assertEqual(meta["swift"]["pbxproj"], [PBXPROJ])

    def test_graph_is_deterministic(self):
        first = build_graph(self.files)
        second = build_graph(self.files)
        self.assertEqual({k: sorted(v) for k, v in first.items()},
                         {k: sorted(v) for k, v in second.items()})


class SynchronizedGroupTests(unittest.TestCase):
    """Xcode 16 moved file lists into folders: Sources phases are empty."""

    @staticmethod
    def files():
        return [
            source("Modules/App/A.swift", "struct A {}\n"),
            source("Modules/App/Sub/B.swift", "struct B { let a = A() }\n"),
            source("Modules/App/Sub/Skip.swift", "struct Skip { let a = A() }\n"),
            source("Other/C.swift", "struct C { let a = A() }\n"),
            source("App.xcodeproj/project.pbxproj", SYNC_PROJECT),
        ]

    def test_a_synchronized_folder_maps_wholesale(self):
        membership = xcode.membership(self.files())
        self.assertEqual(membership["targets"]["App"],
                         ["Modules/App/A.swift", "Modules/App/Sub/B.swift"])

    def test_a_membership_exception_is_not_compiled_by_that_target(self):
        graph = build_graph(self.files())
        self.assertEqual(graph["Modules/App/Sub/B.swift"], {"Modules/App/A.swift"})
        self.assertEqual(graph["Modules/App/Sub/Skip.swift"], set())
        self.assertEqual(graph["Other/C.swift"], set())


class XcodeParserTests(unittest.TestCase):
    def test_a_broken_project_file_yields_no_membership(self):
        files = [
            source("App/A.swift", "struct A {}\n"),
            source("App.xcodeproj/project.pbxproj", "{ objects = { not a plist"),
        ]
        self.assertEqual(xcode.membership(files)["targets"], {})
        self.assertEqual(xcode.membership(files)["pbxproj"], [])

    def test_product_names_are_derived_from_the_product_reference(self):
        project = xcode.parse((FIXTURES / SWIFT / PBXPROJ).read_text())
        self.assertEqual(project.targets["Core"], ["Core/CoreStore.swift"])
        self.assertEqual(project.products["Core"], ["Core"])
        self.assertEqual(project.products["App"], ["App"])


class SwiftGateTests(unittest.TestCase):
    def mixed_tree(self, root):
        for name in (SWIFT, OBJC):
            shutil.copytree(FIXTURES / name, root / name)

    def test_a_mixed_swift_objc_tree_refuses_only_for_documented_reasons(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            out = Path(tmp) / "out"
            repo.mkdir()
            self.mixed_tree(repo)
            result = run(["gate", repo, "--min-loc", "1", "--out", out])
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            scope = json.loads((out / "scope.json").read_text())
        self.assertEqual(sorted(scope["languages"]["supported"]), ["objc", "swift"])
        self.assertEqual(scope["gate"]["reasons"],
                         ["no entrypoints detected (routes, CLI commands, cron jobs, "
                          "consumers, Android components, iOS app/UI classes); "
                          "reachability would be invented"])

    def test_both_documented_gate_reasons_are_reachable_on_a_mixed_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            out = Path(tmp) / "out"
            repo.mkdir()
            self.mixed_tree(repo)
            result = run(["gate", repo, "--min-loc", "100000", "--out", out])
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            scope = json.loads((out / "scope.json").read_text())
        reasons = scope["gate"]["reasons"]
        self.assertEqual(len(reasons), 2, reasons)
        self.assertTrue(reasons[0].startswith("only "), reasons)
        self.assertTrue(reasons[1].startswith("no entrypoints detected"), reasons)

    def test_swift_and_objc_lines_are_both_supported_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            out = Path(tmp) / "out"
            repo.mkdir()
            self.mixed_tree(repo)
            run(["gate", repo, "--min-loc", "1", "--out", out])
            scope = json.loads((out / "scope.json").read_text())
        sizes = {entry["lang"]: entry for entry in scope["size"]["by_language"]}
        self.assertEqual(sorted(sizes), ["objc", "swift"])
        self.assertEqual(scope["size"]["loc"], sizes["swift"]["loc"] + sizes["objc"]["loc"])


class IosEntrypointTests(unittest.TestCase):
    """Swift and Objective-C entrypoints, through the Android chain walker."""

    APP_MAIN = "Signal/AppMain.swift"
    APP_DELEGATE = "Signal/AppDelegate.swift"
    SCENE_DELEGATE = "Signal/WindowSceneDelegate.swift"
    UIKIT_MAIN = "Signal/Main.swift"
    BASE_CONTROLLER = "Signal/BaseViewController.swift"
    CONVERSATION = "Signal/ConversationViewController.swift"
    FEED_VIEW = "Signal/FeedView.swift"
    PLAIN = "Signal/PlainModel.swift"
    OBJC_CONTROLLER = "Signal/ObjC/AccountsViewController.m"
    OBJC_DELEGATE = "Signal/ObjC/LegacyAppDelegate.m"

    @classmethod
    def setUpClass(cls):
        cls.files = fixture_files(IOS)
        cls.entries = extract_entrypoints(cls.files)
        cls.seeds = seeds_from_entrypoints(cls.entries)

    def one(self, rel):
        found = [e for e in self.entries if e["file"] == rel]
        self.assertEqual(len(found), 1, (rel, found))
        return found[0]

    def test_main_attribute_is_ui_with_seed_five(self):
        entry = self.one(self.APP_MAIN)
        self.assertEqual((entry["kind"], entry["detail"]), ("ui", "MAIN"))
        self.assertEqual(self.seeds[self.APP_MAIN], 5)
        self.assertEqual(SEED_BY_KIND["ui"], 5)

    def test_ui_application_main_call_is_ui_with_seed_five(self):
        entry = self.one(self.UIKIT_MAIN)
        self.assertEqual((entry["kind"], entry["detail"]), ("ui", "MAIN"))
        self.assertEqual(self.seeds[self.UIKIT_MAIN], 5)

    def test_app_delegate_conformance_is_app_with_seed_three(self):
        entry = self.one(self.APP_DELEGATE)
        self.assertEqual((entry["kind"], entry["detail"]),
                         ("app", "APPDELEGATE AppDelegate"))
        self.assertEqual(self.seeds[self.APP_DELEGATE], 3)
        self.assertEqual(SEED_BY_KIND["app"], 3)

    def test_scene_delegate_conformance_is_app_with_seed_three(self):
        entry = self.one(self.SCENE_DELEGATE)
        self.assertEqual((entry["kind"], entry["detail"]),
                         ("app", "APPDELEGATE WindowSceneDelegate"))
        self.assertEqual(self.seeds[self.SCENE_DELEGATE], 3)

    def test_a_view_controller_subclass_is_ui_with_seed_five(self):
        entry = self.one(self.BASE_CONTROLLER)
        self.assertEqual((entry["kind"], entry["detail"]),
                         ("ui", "VIEWCONTROLLER BaseViewController"))
        self.assertEqual(self.seeds[self.BASE_CONTROLLER], 5)

    def test_a_view_controller_subclass_is_seeded_through_a_project_base(self):
        entry = self.one(self.CONVERSATION)
        self.assertEqual((entry["kind"], entry["detail"]),
                         ("ui", "VIEWCONTROLLER ConversationViewController"))
        self.assertEqual(self.seeds[self.CONVERSATION], 5)

    def test_a_view_subclass_is_ui_with_seed_five(self):
        entry = self.one(self.FEED_VIEW)
        self.assertEqual((entry["kind"], entry["detail"]),
                         ("ui", "VIEWCONTROLLER FeedView"))
        self.assertEqual(self.seeds[self.FEED_VIEW], 5)

    def test_an_objc_view_controller_seeds_its_implementation(self):
        entry = self.one(self.OBJC_CONTROLLER)
        self.assertEqual((entry["kind"], entry["detail"]),
                         ("ui", "VIEWCONTROLLER AccountsViewController"))
        self.assertEqual(self.seeds[self.OBJC_CONTROLLER], 5)

    def test_an_objc_delegate_seeds_its_implementation(self):
        entry = self.one(self.OBJC_DELEGATE)
        self.assertEqual((entry["kind"], entry["detail"]),
                         ("app", "APPDELEGATE LegacyAppDelegate"))
        self.assertEqual(self.seeds[self.OBJC_DELEGATE], 3)

    def test_a_plain_swift_struct_is_not_seeded(self):
        self.assertEqual([e for e in self.entries if e["file"] == self.PLAIN], [])
        self.assertNotIn(self.PLAIN, self.seeds)

    def test_an_ibaction_handler_is_not_seeded_separately(self):
        entries = extract_entrypoints([
            source("App/FeedViewController.swift",
                   "import UIKit\n"
                   "final class FeedViewController: UIViewController {\n"
                   "    @IBAction func refresh(_ sender: Any) {}\n"
                   "    @IBAction func close(_ sender: Any) {}\n"
                   "}\n")])
        self.assertEqual([(e["kind"], e["detail"]) for e in entries],
                         [("ui", "VIEWCONTROLLER FeedViewController")])

    def test_delegate_conformance_is_not_inherited_from_a_project_base(self):
        entries = extract_entrypoints([
            source("App/BaseAppDelegate.swift",
                   "import UIKit\n"
                   "class BaseAppDelegate: UIResponder, UIApplicationDelegate {}\n"),
            source("App/ChildDelegate.swift",
                   "import UIKit\n"
                   "final class ChildDelegate: BaseAppDelegate {}\n")])
        by_file = {e["file"]: e for e in entries}
        self.assertEqual(by_file["App/BaseAppDelegate.swift"]["kind"], "app")
        self.assertNotIn("App/ChildDelegate.swift", by_file)

    def test_the_chain_walk_stops_after_four_hops(self):
        entries = extract_entrypoints([
            source("App/Leaf.swift", "import UIKit\nfinal class Leaf: Hop1 {}\n"),
            source("App/Hop1.swift", "import UIKit\nclass Hop1: Hop2 {}\n"),
            source("App/Hop2.swift", "import UIKit\nclass Hop2: Hop3 {}\n"),
            source("App/Hop3.swift", "import UIKit\nclass Hop3: Hop4 {}\n"),
            source("App/Hop4.swift", "import UIKit\nclass Hop4: UIViewController {}\n"),
        ])
        seeded = {e["file"] for e in entries}
        self.assertIn("App/Hop1.swift", seeded)     # four edges from Hop1
        self.assertNotIn("App/Leaf.swift", seeded)  # a fifth edge is not followed

    def test_counts_and_seeds_cover_the_ios_kinds(self):
        counts = entrypoint_counts(self.entries)
        self.assertEqual(counts["ui"], 6)
        self.assertEqual(counts["app"], 3)
        self.assertEqual(counts["http"], 0)


class IosGateTests(unittest.TestCase):
    def test_ios_entrypoints_are_enough_for_the_gate_to_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            result = run(["gate", FIXTURES / IOS, "--min-loc", "1", "--out", out])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            scope = json.loads((Path(out) / "scope.json").read_text())
        self.assertTrue(scope["gate"]["ok"])
        self.assertEqual(scope["entrypoint_kinds"]["ui"], 6)
        self.assertEqual(scope["entrypoint_kinds"]["app"], 3)
        self.assertEqual(scope["entrypoints_ignored"], [])


PROJECT = """// !$*UTF8*$!
{
	archiveVersion = 1;
	objects = {
		B1 = {isa = PBXBuildFile; fileRef = F1; };
		B2 = {isa = PBXBuildFile; fileRef = F2; };
		F1 = {isa = PBXFileReference; path = Foo.swift; sourceTree = "<group>"; };
		F2 = {isa = PBXFileReference; path = Bar.swift; sourceTree = "<group>"; };
		G1 = {isa = PBXGroup; children = (F1, F2, ); path = App; sourceTree = "<group>"; };
		S1 = {isa = PBXSourcesBuildPhase; files = (B1, B2, ); };
		T1 = {isa = PBXNativeTarget; buildPhases = (S1, ); name = App; productName = App;
		      productReference = P1; };
		P1 = {isa = PBXFileReference; path = App.app; sourceTree = BUILT_PRODUCTS_DIR; };
	};
	rootObject = R1;
}
"""


SYNC_PROJECT = """// !$*UTF8*$!
{
	archiveVersion = 1;
	objectVersion = 77;
	objects = {
		G0 = {isa = PBXGroup; children = (G1, ); path = Modules; sourceTree = "<group>"; };
		G1 = {isa = PBXFileSystemSynchronizedRootGroup; exceptions = (X1, );
		      path = App; sourceTree = "<group>"; };
		X1 = {isa = PBXFileSystemSynchronizedBuildFileExceptionSet;
		      membershipExceptions = (Sub/Skip.swift, ); };
		S1 = {isa = PBXSourcesBuildPhase; files = (); };
		T1 = {isa = PBXNativeTarget; buildPhases = (S1, );
		      fileSystemSynchronizedGroups = (G1, ); name = App; productName = App;
		      productReference = P1; };
		P1 = {isa = PBXFileReference; path = App.app; sourceTree = BUILT_PRODUCTS_DIR; };
	};
	rootObject = R1;
}
"""


if __name__ == "__main__":
    unittest.main()
