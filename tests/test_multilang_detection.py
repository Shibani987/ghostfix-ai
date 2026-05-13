from __future__ import annotations

import unittest

from core.language_diagnostics import detect_language, diagnose_non_python
from core.runtime_detector import classify_runtime


class MultiLanguageDetectionTests(unittest.TestCase):
    def test_js_reference_error_detected(self):
        output = (
            "C:\\repo\\tests\\manual_multilang_errors\\js_reference_error.js:1\n"
            "console.log(missingValue);\n"
            "            ^\n\n"
            "ReferenceError: missingValue is not defined\n"
            "    at Object.<anonymous> (C:\\repo\\tests\\manual_multilang_errors\\js_reference_error.js:1:13)\n"
        )

        diagnostic = diagnose_non_python(output, command="node tests/manual_multilang_errors/js_reference_error.js")

        self.assertEqual(diagnostic["language"], "javascript/node")
        self.assertEqual(diagnostic["error_type"], "ReferenceError")
        self.assertEqual(diagnostic["root_cause"], "js_reference_error")
        self.assertFalse(diagnostic["auto_fix_available"])

    def test_js_module_not_found_detected(self):
        output = (
            "Error: Cannot find module './missing_local_module'\n"
            "Require stack:\n"
            "- C:\\repo\\tests\\manual_multilang_errors\\js_module_not_found.js\n"
        )

        diagnostic = diagnose_non_python(output, command="node tests/manual_multilang_errors/js_module_not_found.js")

        self.assertEqual(diagnostic["language"], "javascript/node")
        self.assertEqual(diagnostic["error_type"], "Cannot find module")
        self.assertEqual(diagnostic["root_cause"], "js_module_not_found")
        self.assertFalse(diagnostic["auto_fix_available"])

    def test_php_undefined_variable_detected(self):
        output = (
            "PHP Warning:  Undefined variable $missingValue in "
            "C:\\repo\\tests\\manual_multilang_errors\\php_undefined_variable.php on line 2\n"
        )

        diagnostic = diagnose_non_python(output, command="php tests/manual_multilang_errors/php_undefined_variable.php")

        self.assertEqual(diagnostic["language"], "php")
        self.assertEqual(diagnostic["error_type"], "PHP Warning")
        self.assertEqual(diagnostic["root_cause"], "php_undefined_variable")
        self.assertFalse(diagnostic["auto_fix_available"])

    def test_php_parse_error_detected(self):
        output = (
            "PHP Parse error:  Unclosed '{' on line 2 in "
            "C:\\repo\\tests\\manual_multilang_errors\\php_parse_error.php on line 4\n"
        )

        diagnostic = diagnose_non_python(output, command="php tests/manual_multilang_errors/php_parse_error.php")

        self.assertEqual(diagnostic["language"], "php")
        self.assertEqual(diagnostic["error_type"], "PHP Parse error")
        self.assertEqual(diagnostic["root_cause"], "php_parse_error")
        self.assertFalse(diagnostic["auto_fix_available"])
        self.assertEqual(diagnostic["safety_reason"], "Auto-fix is disabled for non-Python languages.")

    def test_runtime_language_classifier_buckets_watch_logs(self):
        self.assertEqual(classify_runtime(command="python app.py", output="Traceback (most recent call last):"), "python")
        self.assertEqual(classify_runtime(command="npm run dev", output="ReferenceError: x is not defined"), "javascript/node")
        self.assertEqual(classify_runtime(command="tsx src/server.ts", output="src/server.ts:4:1"), "typescript")
        self.assertEqual(detect_language(command="custom-server", output="ready\n"), "unknown")

    def test_typescript_stack_trace_is_diagnosis_only(self):
        output = (
            "src/server.ts:3\n"
            "throw new Error('boom')\n"
            "Error: boom\n"
            "    at main (src/server.ts:3:7)\n"
        )

        diagnostic = diagnose_non_python(output, command="tsx src/server.ts")

        self.assertEqual(diagnostic["language"], "typescript")
        self.assertEqual(diagnostic["framework"], "typescript")
        self.assertFalse(diagnostic["auto_fix_available"])

    def test_npm_missing_package_json_gets_specific_diagnosis(self):
        output = (
            "npm ERR! code ENOENT\n"
            "npm ERR! enoent Could not read package.json: Error: ENOENT: no such file or directory, open 'C:\\repo\\package.json'\n"
        )

        diagnostic = diagnose_non_python(output, command="npm run dev")

        self.assertEqual(diagnostic["error_type"], "NpmPackageJsonMissingError")
        self.assertIn("outside a Node project", diagnostic["likely_root_cause"])
        self.assertIn("npm init", diagnostic["suggested_fix"])


if __name__ == "__main__":
    unittest.main()
