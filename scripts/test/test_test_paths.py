import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.walk import is_test_path


class TestPathTests(unittest.TestCase):
    def test_jvm_test_directories(self):
        for path in ("app/src/androidTest/java/A/Foo.kt",
                     "src/test/java/com/x/Foo.java",
                     "app/src/test/kotlin/Foo.kt"):
            self.assertTrue(is_test_path(path), path)

    def test_jvm_test_file_names(self):
        for path in ("src/FooTest.java", "src/FooTests.kt", "src/FooIT.java", "src/FooSpec.kt"):
            self.assertTrue(is_test_path(path), path)

    def test_python_and_js_test_names(self):
        for path in ("tests/test_api.py", "pkg/test_thing.py", "web/thing.test.ts", "web/x.spec.js"):
            self.assertTrue(is_test_path(path), path)

    def test_production_code_is_not_a_test(self):
        for path in ("src/main/java/Foo.java", "app/src/main/kotlin/Test.kt",
                     "scripts/lib/context.py", "web/app.ts"):
            self.assertFalse(is_test_path(path), path)


if __name__ == "__main__":
    unittest.main()
