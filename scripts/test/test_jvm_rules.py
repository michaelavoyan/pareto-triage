"""JVM rules: one planted defect per rule, and a line that must stay quiet."""

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
FIXTURE = FIXTURES / "jvm-rules"
PREFIX = "src/main/java/com/acme/"
KOTLIN = "src/main/kotlin/com/acme/"
SAFE = PREFIX + "SafeCounterparts.java"
CLEAN = [SAFE, PREFIX + "ConstantExec.java", PREFIX + "KeyedCallback.java",
         # Log-then-throw and log-then-return were the shapes a rejected
         # log-only-catch rule had to stay silent on. They remain silent here
         # because neither body is empty.
         PREFIX + "LogThenThrow.java", PREFIX + "CatchReturnsError.java",
         # The five mechanically false jvm-empty-catch findings from the
         # Signal-Android audit. The rule is withdrawn; these files prove the
         # masking helper does not read their literal bodies as empty.
         KOTLIN + "NameCollisionTables.kt", KOTLIN + "LogSectionSystemInfo.kt",
         KOTLIN + "RingRtcDynamicConfiguration.kt", KOTLIN + "WebView.kt"]

sys.path.insert(0, str(SCRIPTS))
from lib.rules import _blank_noncode, detect_defects  # noqa: E402
from lib.schema import validate_finding  # noqa: E402

EXPECTED = {
    PREFIX + "ExecInjection.java": "jvm-exec-injection",
    PREFIX + "SqlInjection.java": "jvm-sql-injection",
    PREFIX + "WeakHash.java": "jvm-weak-hash",
    PREFIX + "WeakHashBucketing.java": "jvm-weak-hash",
    PREFIX + "ObjectInput.java": "jvm-object-input-stream",
}

AXES = {
    "jvm-exec-injection": ("command-injection", 5, 2),
    "jvm-sql-injection": ("sql-injection", 5, 2),
    "jvm-weak-hash": ("weak-hash", 3, 3),
    "jvm-object-input-stream": ("unsafe-deserialization", 5, 3),
}


def run(args):
    return subprocess.run([sys.executable, str(CLI)] + [str(a) for a in args],
                          capture_output=True, text=True)


def source(rel, text):
    return {"rel": rel, "ext": posixpath.splitext(rel)[1], "text": text}


class JvmFixtureTests(unittest.TestCase):
    """One planted defect per rule, and one file that must stay silent."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls._tmp.name)
        gate = run(["gate", FIXTURE, "--min-loc", "1", "--out", cls.out])
        assert gate.returncode == 0, gate.stdout + gate.stderr
        detect = run(["detect", FIXTURE, "--out", cls.out])
        assert detect.returncode == 0, detect.stdout + detect.stderr
        cls.findings = [json.loads(line) for line in
                        (cls.out / "defects.jsonl").read_text().splitlines() if line.strip()]

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_each_rule_fires_on_its_own_fixture(self):
        self.assertEqual(sorted((f["file"], f["rule"]) for f in self.findings),
                         sorted(EXPECTED.items()))
        for rule in EXPECTED.values():
            self.assertTrue(any(f["rule"] == rule for f in self.findings), rule)

    def test_the_safe_counterparts_are_clean(self):
        for rel in CLEAN:
            self.assertEqual([f for f in self.findings if f["file"] == rel], [], rel)

    def test_findings_are_tool_detected_defects_with_the_documented_axes(self):
        self.assertEqual(len(self.findings), len(EXPECTED))
        for finding in self.findings:
            self.assertEqual(finding["class"], "defect")
            self.assertEqual(finding["detector"], "tool")
            # The fixture ships no test runner, so the rubric caps confidence at
            # "med" and records the reason. Either way the rule is a tool proof.
            self.assertIn(finding["confidence"], ("high", "med"))
            if finding["confidence"] == "med":
                self.assertTrue(finding.get("confidence_capped"))
                self.assertEqual(finding.get("confidence_reason"), "no test runner detected")
            self.assertEqual((finding["taxonomy"], finding["blast"], finding["silence"]),
                             AXES[finding["rule"]])

    def test_detect_output_validates_against_the_sources(self):
        sources = {p.relative_to(FIXTURE).as_posix(): p.read_text(encoding="utf-8")
                   for p in FIXTURE.rglob("*") if p.is_file()}
        for finding in self.findings:
            self.assertEqual(validate_finding(finding, sources=sources), [], finding["id"])


class NoncodeMaskTests(unittest.TestCase):
    """A literal is code: masking it away must not invent an empty body."""

    CATCH = re.compile(r"\bcatch\s*\([^)]*\)\s*\{")

    @classmethod
    def catch_bodies(cls, text):
        blanked = _blank_noncode(text)
        bodies = []
        for match in cls.CATCH.finditer(blanked):
            depth = 1
            cursor = match.end()
            while cursor < len(blanked) and depth:
                if blanked[cursor] == "{":
                    depth += 1
                elif blanked[cursor] == "}":
                    depth -= 1
                cursor += 1
            bodies.append(blanked[match.end():cursor - 1])
        return bodies

    def test_the_mask_keeps_offsets(self):
        text = 'val s = "a { b } c" // }\n'
        self.assertEqual(len(_blank_noncode(text)), len(text))

    def test_a_comment_only_body_still_reads_as_empty(self):
        text = "try {\n    go();\n} catch (IOException e) {\n    // ignored\n}\n"
        self.assertEqual([body.strip() for body in self.catch_bodies(text)], [""])

    def test_a_block_comment_only_body_still_reads_as_empty(self):
        text = "try {\n    go();\n} catch (IOException e) {\n    /* ignored */\n}\n"
        self.assertEqual([body.strip() for body in self.catch_bodies(text)], [""])

    def test_braces_inside_a_literal_do_not_end_the_body(self):
        text = 'try {\n    go();\n} catch (Exception e) {\n    log("}");\n}\n'
        bodies = self.catch_bodies(text)
        self.assertEqual(len(bodies), 1)
        self.assertTrue(bodies[0].strip())

    def test_the_five_signal_shapes_are_not_empty_bodies(self):
        cases = {
            "NameCollisionTables.kt": 1,        # return ""
            "LogSectionSystemInfo.kt": 1,       # return "Unknown"
            "RingRtcDynamicConfiguration.kt": 2,  # two returns of ""
            "WebView.kt": 1,                    # return "Error... ${e.message}"
        }
        for name, count in cases.items():
            text = (FIXTURE / KOTLIN / name).read_text(encoding="utf-8")
            bodies = self.catch_bodies(text)
            self.assertEqual(len(bodies), count, name)
            for body in bodies:
                self.assertTrue(body.strip(),
                                "%s: a literal body was masked to an empty body" % name)


class JvmRuleTests(unittest.TestCase):
    """The positive fixture is one line per rule; these cover the alternatives."""

    def rules(self, rel, text):
        findings, _ = detect_defects([source(rel, text)])
        return [(f["rule"], f["line"], f["evidence"]) for f in findings]

    def test_process_builder_with_concatenation_also_fires(self):
        text = 'ProcessBuilder builder = new ProcessBuilder("sh " + script);\n'
        self.assertEqual(self.rules("A.java", text),
                         [("jvm-exec-injection", 1, text.strip())])

    def test_exec_without_concatenation_is_quiet(self):
        self.assertEqual(self.rules("A.java", 'Runtime.getRuntime().exec("ls");\n'), [])

    def test_exec_with_a_constant_operand_is_quiet(self):
        text = 'Runtime.getRuntime().exec("logcat -d " + FILTER_SPEC);\n'
        self.assertEqual(self.rules("A.java", text), [])

    def test_exec_with_a_qualified_constant_is_quiet(self):
        text = 'new ProcessBuilder("logcat -d " + BuildConfig.LOG_FILTER).start();\n'
        self.assertEqual(self.rules("A.java", text), [])

    def test_exec_with_literal_operands_only_is_quiet(self):
        text = 'Runtime.getRuntime().exec("ls " + "-l");\n'
        self.assertEqual(self.rules("A.java", text), [])

    def test_exec_with_a_method_call_operand_fires(self):
        text = 'Runtime.getRuntime().exec("convert " + options.render());\n'
        self.assertEqual(self.rules("A.java", text),
                         [("jvm-exec-injection", 1, text.strip())])

    def test_exec_with_a_lowercase_parameter_fires(self):
        text = 'Runtime.getRuntime().exec("convert " + path);\n'
        self.assertEqual(self.rules("A.java", text),
                         [("jvm-exec-injection", 1, text.strip())])

    def test_exec_with_a_constant_and_a_value_fires(self):
        text = 'Runtime.getRuntime().exec("logcat -d " + FILTER_SPEC + path);\n'
        self.assertEqual(self.rules("A.java", text),
                         [("jvm-exec-injection", 1, text.strip())])

    def test_commented_exec_is_quiet(self):
        self.assertEqual(self.rules("A.java", '// Runtime.getRuntime().exec("rm " + p);\n'), [])

    def test_exec_inside_a_string_is_quiet(self):
        text = 'String cmd = "Runtime.getRuntime().exec(\\"rm \\" + p)";\n'
        self.assertEqual(self.rules("A.java", text), [])

    def test_sql_without_concatenation_is_quiet(self):
        self.assertEqual(self.rules("A.java",
                                    'stmt.executeQuery("SELECT * FROM t WHERE id = ?");\n'), [])

    def test_sql_on_a_keyed_executor_is_quiet(self):
        text = 'keyedExecutor.execute("Call::" + info.getRecipientId(), () -> {\n'
        self.assertEqual(self.rules("A.java", text), [])

    def test_sql_with_a_concatenated_identifier_but_no_verb_is_quiet(self):
        text = 'keyedExecutor.execute(TASK_PREFIX + recipientId);\n'
        self.assertEqual(self.rules("A.java", text), [])

    def test_sql_with_a_verb_and_concatenation_still_fires(self):
        for text in (
            'stmt.executeQuery("SELECT * FROM t WHERE id = \'" + id + "\'");\n',
            'stmt.executeUpdate("UPDATE t SET x = " + value);\n',
            'stmt.execute("DELETE FROM t WHERE id = " + id);\n',
            'stmt.execute("REPLACE INTO t VALUES (" + value + ")");\n',
        ):
            self.assertEqual(self.rules("A.java", text),
                             [("jvm-sql-injection", 1, text.strip())], text)

    def test_sha256_is_not_a_weak_hash(self):
        self.assertEqual(self.rules("A.java",
                                    'MessageDigest.getInstance("SHA-256");\n'), [])

    def test_a_bucketing_key_still_fires_and_carries_blast_3(self):
        text = (FIXTURE / PREFIX / "WeakHashBucketing.java").read_text(encoding="utf-8")
        findings, _ = detect_defects([source(PREFIX + "WeakHashBucketing.java", text)])
        self.assertEqual([(f["rule"], f["blast"]) for f in findings],
                         [("jvm-weak-hash", 3)])

    def test_object_output_stream_is_not_deserialization(self):
        self.assertEqual(self.rules("A.java", "new ObjectOutputStream(stream);\n"), [])

    def test_kotlin_and_gradle_scripts_are_scanned(self):
        findings, _ = detect_defects([
            source("A.kt", 'fun run(p: String) {\n    Runtime.getRuntime().exec("sh " + p)\n}\n'),
            source("build.gradle.kts", 'val md = MessageDigest.getInstance("SHA-1")\n'),
        ])
        self.assertEqual(sorted((f["file"], f["rule"]) for f in findings),
                         [("A.kt", "jvm-exec-injection"),
                          ("build.gradle.kts", "jvm-weak-hash")])

    def test_jvm_files_get_the_shared_secret_rules(self):
        for ext in (".java", ".kt", ".kts"):
            findings, _ = detect_defects(
                [source("Key" + ext, 'String key = "AKIAABCDEFGHIJKLMNOP";\n')])
            self.assertEqual([f["rule"] for f in findings], ["py-secret-aws"], ext)
        findings, _ = detect_defects([source("Key.kt", "# -----BEGIN RSA PRIVATE KEY-----\n")])
        self.assertEqual([f["rule"] for f in findings], ["py-secret-pem"])


if __name__ == "__main__":
    unittest.main()
