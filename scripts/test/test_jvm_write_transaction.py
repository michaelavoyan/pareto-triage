"""`jvm-write-without-transaction` was withdrawn; its fixtures stay silent.

The rule fired on every method with two writes and no transaction call in the
body. Measured on Signal-Android, 5 of 230 findings were true; the rest were a
transaction the method did not contain (withinTransaction, the caller's
`ensureInTransaction`, or the framework's onCreate/onUpgrade transaction),
mutually exclusive branches, or deliberate independent writes. JobPilot has no
JVM source, so incidence there was zero. The two fixtures remain so a future
proposal has to make this test fail before it ships.
"""

import posixpath
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
FIXTURES = SCRIPTS.parent / "fixtures" / "jvm-rules"

sys.path.insert(0, str(SCRIPTS))
from lib.rules import META, detect_defects  # noqa: E402


def source(rel, text):
    return {"rel": rel, "ext": posixpath.splitext(rel)[1], "text": text}


class WithdrawnWriteTransactionTests(unittest.TestCase):
    def detect(self, text, rel):
        findings, _ = detect_defects([source(rel, text)])
        return findings

    def test_the_rule_is_not_shipped(self):
        self.assertNotIn("jvm-write-without-transaction", META)

    def test_two_writes_with_no_transaction_produce_no_finding(self):
        text = (
            "public final class A {\n"
            "    void transfer(SQLiteDatabase db) {\n"
            "        db.insert(TABLE, null, values);\n"
            "        db.update(TABLE, values, \"id = ?\", args);\n"
            "    }\n"
            "}\n"
        )
        self.assertEqual(self.detect(text, "A.java"), [])

    def test_the_fixture_pair_produces_no_finding(self):
        names = ("NonAtomicWrite.java", "TransactionalWrite.java")
        files = [source(name, (FIXTURES / "src/main/java/com/acme" / name)
                        .read_text(encoding="utf-8")) for name in names]
        findings, _ = detect_defects(files)
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
