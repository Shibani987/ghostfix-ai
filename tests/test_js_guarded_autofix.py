from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from agent.terminal_watcher import TerminalWatcher
from core.js_autofix import build_js_patch_plan
from core.language_diagnostics import diagnose_non_python
from core.patch_validator import PatchValidator


class JsGuardedAutofixTests(unittest.TestCase):
    def test_missing_semicolon_can_generate_guarded_patch_preview(self):
        with _node_project() as root:
            target = root / "src" / "index.js"
            target.write_text("const value = 1\nconsole.log(value)\n", encoding="utf-8")
            diagnostic = diagnose_non_python(
                "SyntaxError: Unexpected identifier\n    at main (src/index.js:1:16)\n",
                command="node src/index.js",
                cwd=str(root),
            )

        self.assertTrue(diagnostic["auto_fix_available"])
        self.assertTrue(diagnostic["safe_to_autofix"])
        self.assertIn("+const value = 1;", diagnostic["patch_preview"])
        self.assertEqual(diagnostic["patch_block"]["language"], "javascript/typescript")

    def test_relative_import_extension_patch_requires_exact_target(self):
        with _node_project() as root:
            app = root / "src" / "app.js"
            helper = root / "src" / "helper.js"
            app.write_text("import { helper } from './helper'\nconsole.log(helper)\n", encoding="utf-8")
            helper.write_text("export const helper = 1;\n", encoding="utf-8")
            diagnostic = diagnose_non_python(
                "Error: Cannot find module './helper'\n    at main (src/app.js:1:1)\n",
                command="node src/app.js",
                cwd=str(root),
            )

        self.assertTrue(diagnostic["auto_fix_available"])
        self.assertIn("from './helper.js'", diagnostic["patch_preview"])

    def test_js_patch_validator_applies_with_backup_after_confirmation_path(self):
        with _node_project() as root:
            target = root / "src" / "index.js"
            target.write_text("const value = 1\n", encoding="utf-8")
            diagnostic = diagnose_non_python(
                "SyntaxError: Unexpected identifier\n    at main (src/index.js:1:16)\n",
                command="node src/index.js",
                cwd=str(root),
            )
            result = PatchValidator().apply_with_backup_and_compile(diagnostic["patch_block"])

            self.assertTrue(result["applied"], result)
            self.assertTrue(Path(result["backup"]).exists())
            self.assertIn("const value = 1;", target.read_text(encoding="utf-8"))
            self.assertTrue(result["rollback_metadata"]["backup"])

    def test_unsafe_js_runtime_error_stays_suggestion_only(self):
        with _node_project() as root:
            diagnostic = diagnose_non_python(
                "POST /api/generate 500 in 98ms\n"
                "Error: Could not connect to Ollama. Make sure Ollama is running at OLLAMA_BASE_URL.\n",
                command="npm run dev",
                cwd=str(root),
            )

        self.assertFalse(diagnostic["auto_fix_available"])
        self.assertIn("external service/config issue", diagnostic["why_auto_fix_blocked"])

    def test_watch_apply_js_patch_can_be_declined_without_write(self):
        with _node_project() as root:
            target = root / "src" / "index.js"
            original = "const value = 1\n"
            target.write_text(original, encoding="utf-8")
            diagnostic = diagnose_non_python(
                "SyntaxError: Unexpected identifier\n    at main (src/index.js:1:16)\n",
                command="node src/index.js",
                cwd=str(root),
            )
            watcher = TerminalWatcher("node src/index.js", cwd=str(root), auto_fix=True, verbose=False)

            with patch("rich.prompt.Confirm.ask", return_value=False), redirect_stdout(StringIO()) as output:
                watcher._handle_language_diagnostic(diagnostic)

            self.assertEqual(target.read_text(encoding="utf-8"), original)
            self.assertIn("PATCH_PREVIEW:", output.getvalue())
            self.assertIn("No code was changed", output.getvalue())


class _node_project:
    def __enter__(self) -> Path:
        self._temp = tempfile.TemporaryDirectory()
        root = Path(self._temp.name)
        (root / "package.json").write_text(
            json.dumps({"scripts": {"dev": "node src/index.js"}, "dependencies": {"express": "4.18.0"}}),
            encoding="utf-8",
        )
        (root / "src").mkdir()
        return root

    def __exit__(self, exc_type, exc, tb) -> None:
        self._temp.cleanup()


if __name__ == "__main__":
    unittest.main()
