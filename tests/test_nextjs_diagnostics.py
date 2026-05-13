from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from agent.terminal_watcher import TerminalWatcher
from core.language_diagnostics import diagnose_non_python
from core.parser import extract_runtime_error


class NextJsDiagnosticsTests(unittest.TestCase):
    def test_next_module_not_found_has_contextual_suggestion(self):
        with _next_project() as root:
            output = (
                "ready - started server on 0.0.0.0:3000\n"
                "Module not found: Can't resolve '@/components/MissingCard'\n"
                "\n"
                "Import trace for requested module:\n"
                "./app/page.tsx\n"
            )

            diagnostic = diagnose_non_python(output, command="npm run dev", cwd=str(root))

        self.assertEqual(diagnostic["framework"], "next.js")
        self.assertEqual(diagnostic["error_type"], "ModuleNotFoundError")
        self.assertFalse(diagnostic["auto_fix_available"])
        self.assertFalse(diagnostic["safe_to_autofix"])
        self.assertIn("tsconfig/jsconfig path aliases", diagnostic["suggested_fix"])
        self.assertTrue(any("app directory" in item for item in diagnostic["evidence"]))

    def test_next_env_missing_is_suggestion_only(self):
        with _next_project() as root:
            diagnostic = diagnose_non_python(
                "Error: Missing required environment variable NEXT_PUBLIC_API_URL\n",
                command="next dev",
                cwd=str(root),
            )

        self.assertEqual(diagnostic["error_type"], "MissingEnvironmentVariable")
        self.assertIn("NEXT_PUBLIC_API_URL", diagnostic["suggested_fix"])
        self.assertFalse(diagnostic["auto_fix_available"])

    def test_typescript_and_hydration_rules(self):
        with _next_project() as root:
            ts = diagnose_non_python(
                "Type error: Type 'string' is not assignable to type 'number'.\n",
                command="pnpm dev",
                cwd=str(root),
            )
            hydration = diagnose_non_python(
                "Error: Hydration failed because the server rendered HTML didn't match the client.\n",
                command="next dev",
                cwd=str(root),
            )

        self.assertEqual(ts["error_type"], "TypeScriptError")
        self.assertIn("type contract mismatch", ts["likely_root_cause"])
        self.assertEqual(hydration["error_type"], "ReactHydrationError")
        self.assertIn("server and client", hydration["likely_root_cause"])
        self.assertFalse(hydration["auto_fix_available"])

    def test_parser_extracts_next_build_error(self):
        extracted = extract_runtime_error(
            "wait - compiling /page\n"
            "Failed to compile\n"
            "./app/page.tsx:10:5\n"
            "Parsing ecmascript source code failed\n"
            "Unexpected token `div`. Expected jsx identifier\n",
            command="next dev",
        )

        self.assertEqual(extracted["framework"], "next.js")
        self.assertEqual(extracted["kind"], "next_error")
        self.assertEqual(extracted["type"], "BuildSyntaxError")

    def test_watch_language_diagnostic_prints_no_code_changed(self):
        with _next_project() as root:
            watcher = TerminalWatcher("npm run dev", cwd=str(root), auto_fix=False, verbose=False)
            diagnostic = diagnose_non_python(
                "Module not found: Can't resolve 'date-fns'\nImport trace for requested module:\n./app/page.tsx\n",
                command="npm run dev",
                cwd=str(root),
            )
            with redirect_stdout(StringIO()) as output:
                watcher._handle_language_diagnostic(diagnostic)

        text = output.getvalue()
        self.assertIn("ERROR: ModuleNotFoundError", text)
        self.assertIn("AUTO_FIX: no", text)
        self.assertIn("No code was changed", text)

    def test_next_ollama_runtime_error_has_route_and_suggestion(self):
        with _next_project() as root:
            output = (
                "ready - started server on 0.0.0.0:3000\n"
                "POST /api/chat 500 in 1532ms\n"
                "Error: Could not connect to Ollama. Make sure Ollama is running at OLLAMA_BASE_URL.\n"
                "    at POST (app/api/chat/route.ts:42:11)\n"
            )

            diagnostic = diagnose_non_python(output, command="npm run dev", cwd=str(root))

        self.assertEqual(diagnostic["framework"], "next.js")
        self.assertEqual(diagnostic["error_type"], "OllamaConnectionError")
        self.assertEqual(diagnostic["route"], "/api/chat")
        self.assertIn("OLLAMA_BASE_URL", diagnostic["likely_root_cause"])
        self.assertIn("Start Ollama", diagnostic["suggested_fix"])
        self.assertFalse(diagnostic["auto_fix_available"])
        self.assertFalse(diagnostic["safe_to_autofix"])

    def test_next_localhost_econnrefused_is_dependency_suggestion(self):
        with _next_project() as root:
            diagnostic = diagnose_non_python(
                "GET /api/generate 500 in 811ms\n"
                "TypeError: fetch failed\n"
                "cause: Error: connect ECONNREFUSED 127.0.0.1:11434\n",
                command="next dev",
                cwd=str(root),
            )

        self.assertEqual(diagnostic["error_type"], "ConnectionRefusedError")
        self.assertEqual(diagnostic["route"], "/api/generate")
        self.assertIn("127.0.0.1:11434", diagnostic["likely_root_cause"])
        self.assertIn("dependent local service", diagnostic["suggested_fix"])
        self.assertFalse(diagnostic["auto_fix_available"])
        self.assertIn("external service/config issue", diagnostic["why_auto_fix_blocked"])

    def test_next_api_route_500_gets_backend_dependency_suggestion(self):
        with _next_project() as root:
            diagnostic = diagnose_non_python(
                "POST /api/generate-resume 500 in 1201ms\n"
                "Error: upstream resume service failed with status 500\n",
                command="npm run dev",
                cwd=str(root),
            )

        self.assertEqual(diagnostic["error_type"], "Http500Error")
        self.assertEqual(diagnostic["route"], "/api/generate-resume")
        self.assertIn("server-side route/API handler", diagnostic["likely_root_cause"])
        self.assertFalse(diagnostic["auto_fix_available"])

    def test_watch_streaming_next_runtime_error_emits_one_diagnosis(self):
        with _next_project() as root:
            watcher = TerminalWatcher("npm run dev", cwd=str(root), auto_fix=False, verbose=False)
            lines = [
                "ready - started server on 0.0.0.0:3000\n",
                "POST /api/chat 500 in 1532ms\n",
                "Error: Could not connect to Ollama. Make sure Ollama is running at OLLAMA_BASE_URL.\n",
                "Error: Could not connect to Ollama. Make sure Ollama is running at OLLAMA_BASE_URL.\n",
            ]
            with redirect_stdout(StringIO()) as output:
                for line in lines:
                    watcher._maybe_handle_streaming_language_error(line)

        text = output.getvalue()
        self.assertIn("ERROR: OllamaConnectionError", text)
        self.assertIn("ROOT_CAUSE:", text)
        self.assertIn("SUGGESTED_FIX", text)
        self.assertIn("ROUTE: /api/chat", text)
        self.assertIn("AUTO_FIX: no", text)
        self.assertEqual(text.count("STATUS: error"), 1)
        self.assertEqual(text.count("ERROR: OllamaConnectionError"), 1)

    def test_express_port_conflict_has_framework_specific_suggestion(self):
        with _express_project() as root:
            diagnostic = diagnose_non_python(
                "Error: listen EADDRINUSE: address already in use :::3000\n",
                command="node server.js",
                cwd=str(root),
            )

        self.assertEqual(diagnostic["framework"], "express")
        self.assertEqual(diagnostic["error_type"], "EADDRINUSE")
        self.assertIn("Express", diagnostic["likely_root_cause"])
        self.assertFalse(diagnostic["auto_fix_available"])


class _next_project:
    def __enter__(self) -> Path:
        self._temp = tempfile.TemporaryDirectory()
        root = Path(self._temp.name)
        (root / "package.json").write_text(
            json.dumps(
                {
                    "scripts": {"dev": "next dev"},
                    "dependencies": {"next": "15.0.0", "react": "19.0.0", "typescript": "5.0.0"},
                }
            ),
            encoding="utf-8",
        )
        (root / "next.config.js").write_text("module.exports = {}\n", encoding="utf-8")
        (root / "tsconfig.json").write_text('{"compilerOptions":{"paths":{"@/*":["./*"]}}}\n', encoding="utf-8")
        (root / "app").mkdir()
        (root / "src").mkdir()
        (root / "app" / "page.tsx").write_text("export default function Page() { return null }\n", encoding="utf-8")
        return root

    def __exit__(self, exc_type, exc, tb) -> None:
        self._temp.cleanup()


class _express_project:
    def __enter__(self) -> Path:
        self._temp = tempfile.TemporaryDirectory()
        root = Path(self._temp.name)
        (root / "package.json").write_text(
            json.dumps({"scripts": {"dev": "node server.js"}, "dependencies": {"express": "4.18.0"}}),
            encoding="utf-8",
        )
        (root / "server.js").write_text("const express = require('express')\n", encoding="utf-8")
        return root

    def __exit__(self, exc_type, exc, tb) -> None:
        self._temp.cleanup()
