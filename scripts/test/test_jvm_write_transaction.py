"""jvm-write-without-transaction: two writes with no transaction in the method."""

import posixpath
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
FIXTURES = SCRIPTS.parent / "fixtures" / "jvm-rules"

sys.path.insert(0, str(SCRIPTS))
from lib.rules import detect_defects  # noqa: E402


def source(rel, text):
    return {"rel": rel, "ext": posixpath.splitext(rel)[1], "text": text}


class WriteWithoutTransactionTests(unittest.TestCase):
    def rules(self, text, rel="A.java"):
        findings, _ = detect_defects([source(rel, text)])
        return [(f["rule"], f["line"], f["evidence"]) for f in findings]

    def test_two_writes_with_no_transaction_fire_once(self):
        text = (
            "public final class A {\n"
            "    void transfer(SQLiteDatabase db) {\n"
            "        db.insert(TABLE, null, values);\n"
            "        db.update(TABLE, values, \"id = ?\", args);\n"
            "    }\n"
            "}\n"
        )
        self.assertEqual([(rule, line) for rule, line, _ in self.rules(text)],
                         [("jvm-write-without-transaction", 3)])

    def test_a_transaction_call_in_the_method_silences_it(self):
        for call in ("beginTransaction()", "endTransaction()", "inTransaction {",
                     "withTransaction {"):
            text = (
                "public final class A {\n"
                "    void transfer(SQLiteDatabase db) {\n"
                "        db.%s\n"
                "        db.insert(TABLE, null, values);\n"
                "        db.delete(TABLE, \"id = ?\", args);\n"
                "    }\n"
                "}\n" % call
            )
            self.assertEqual(self.rules(text), [], call)

    def test_one_write_is_silent(self):
        text = (
            "public final class A {\n"
            "    void rename(SQLiteDatabase db) {\n"
            "        db.update(TABLE, values, \"id = ?\", args);\n"
            "    }\n"
            "}\n"
        )
        self.assertEqual(self.rules(text), [])

    def test_writes_in_comments_and_literals_do_not_count(self):
        text = (
            "public final class A {\n"
            "    void rename(SQLiteDatabase db) {\n"
            "        // db.insert(TABLE, null, values);\n"
            "        String sql = \"update jobs set x = 1\";\n"
            "        db.update(TABLE, values, \"id = ?\", args);\n"
            "    }\n"
            "}\n"
        )
        self.assertEqual(self.rules(text), [])

    def test_a_class_body_is_not_a_method(self):
        text = (
            "public final class A {\n"
            "    void one(SQLiteDatabase db) { db.insert(TABLE, null, values); }\n"
            "    void two(SQLiteDatabase db) { db.delete(TABLE, \"id = ?\", args); }\n"
            "}\n"
        )
        self.assertEqual(self.rules(text), [])

    def test_kotlin_methods_fire(self):
        text = (
            "class A {\n"
            "    fun transfer(db: SQLiteDatabase) {\n"
            "        db.insert(TABLE, null, values)\n"
            "        db.delete(TABLE, \"id = ?\", args)\n"
            "    }\n"
            "}\n"
        )
        self.assertEqual([rule for rule, _, _ in self.rules(text, "A.kt")],
                         ["jvm-write-without-transaction"])

    def test_the_fixture_pairs_a_firing_method_with_silent_ones(self):
        findings, _ = detect_defects([
            {"rel": "NonAtomicWrite.java", "ext": ".java",
             "text": (FIXTURES / "src/main/java/com/acme/NonAtomicWrite.java")
             .read_text(encoding="utf-8")},
            {"rel": "TransactionalWrite.java", "ext": ".java",
             "text": (FIXTURES / "src/main/java/com/acme/TransactionalWrite.java")
             .read_text(encoding="utf-8")},
        ])
        self.assertEqual([(f["file"], f["rule"]) for f in findings],
                         [("NonAtomicWrite.java", "jvm-write-without-transaction")])


if __name__ == "__main__":
    unittest.main()
