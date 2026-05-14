from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import ANY, patch

from agent.terminal_watcher import TerminalWatcher
from core.language_diagnostics import diagnose_non_python
from core.patch_validator import PatchValidator


class FrameworkFixerV08Tests(unittest.TestCase):
    def test_next_ollama_unreachable_generates_safe_code_guard_patch(self):
        with _next_ollama_project() as root, patch("subprocess.run", return_value=_ok_build()) as run:
            diagnostic = diagnose_non_python(_ollama_log(), command="npm run dev", cwd=str(root))

        self.assertTrue(diagnostic["auto_fix_available"], diagnostic.get("why_auto_fix_blocked"))
        self.assertEqual(diagnostic["patch_block"]["action"], "framework_multi_file")
        self.assertEqual(diagnostic["route"], "/api/generate-resume")
        patch_text = diagnostic["patch_preview"]
        self.assertIn("preflightOllama", patch_text)
        self.assertIn("/api/tags", patch_text)
        self.assertIn("OLLAMA_TIMEOUT_MS", patch_text)
        self.assertIn("Ollama model", patch_text)
        self.assertIn(".env.example", patch_text)
        run.assert_any_call(
            ["npm", "run", "build"],
            cwd=ANY,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,
        )

    def test_env_local_never_modified_but_env_example_may_be_updated(self):
        with _next_ollama_project() as root, patch("subprocess.run", return_value=_ok_build()):
            env_local = root / ".env.local"
            env_local.write_text("OLLAMA_BASE_URL=http://secret-local\n", encoding="utf-8")
            diagnostic = diagnose_non_python(_ollama_log(), command="npm run dev", cwd=str(root))
            block = diagnostic["patch_block"]
            env_local_text = env_local.read_text(encoding="utf-8")

        targets = [Path(item["file_path"]).name for item in block["files"]]
        self.assertNotIn(".env.local", targets)
        self.assertIn(".env.example", targets)
        self.assertEqual(env_local_text, "OLLAMA_BASE_URL=http://secret-local\n")

    def test_npm_run_build_validation_is_required(self):
        with _next_ollama_project() as root, patch("subprocess.run", return_value=_ok_build()):
            diagnostic = diagnose_non_python(_ollama_log(), command="npm run dev", cwd=str(root))
            block = diagnostic["patch_block"]
            block["validation_commands"] = []
            validation = PatchValidator().validate(block)

        self.assertFalse(validation.ok)
        self.assertIn("npm run build", validation.reason)

    def test_build_failure_blocks_ollama_framework_patch(self):
        with _next_ollama_project() as root, patch("subprocess.run", return_value=_failed_build()):
            diagnostic = diagnose_non_python(_ollama_log(), command="npm run dev", cwd=str(root))

        self.assertFalse(diagnostic["auto_fix_available"])
        self.assertIn("Project validation failed", diagnostic["why_auto_fix_blocked"])

    def test_watch_apply_framework_patch_asks_and_creates_backups(self):
        with _next_ollama_project() as root, patch("subprocess.run", return_value=_ok_build()):
            diagnostic = diagnose_non_python(_ollama_log(), command="npm run dev", cwd=str(root))
            watcher = TerminalWatcher("npm run dev", cwd=str(root), auto_fix=True, verbose=False)

            with patch("rich.prompt.Confirm.ask", return_value=True), redirect_stdout(StringIO()) as output:
                watcher._handle_language_diagnostic(diagnostic)

            text = output.getvalue()
            agent = root / "lib" / "ai" / "resumeAgent.ts"
            self.assertIn("Backup created:", text)
            self.assertIn("Rollback is available.", text)
            self.assertIn("preflightOllama", agent.read_text(encoding="utf-8"))
            self.assertTrue(list((root / "lib" / "ai").glob("resumeAgent.ts.bak_*")))

    def test_unsafe_ollama_case_without_exact_route_file_stays_blocked(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch("subprocess.run", return_value=_ok_build()):
            root = Path(temp_dir)
            (root / "package.json").write_text(
                json.dumps({"scripts": {"build": "next build", "dev": "next dev"}, "dependencies": {"next": "15.0.0"}}),
                encoding="utf-8",
            )
            diagnostic = diagnose_non_python(_ollama_log(), command="npm run dev", cwd=str(root))

        self.assertFalse(diagnostic["auto_fix_available"])
        self.assertIn("No exact local Next.js route file", diagnostic["why_auto_fix_blocked"])


class _next_ollama_project:
    def __enter__(self) -> Path:
        self._temp = tempfile.TemporaryDirectory()
        root = Path(self._temp.name)
        (root / "package.json").write_text(
            json.dumps(
                {
                    "scripts": {"dev": "next dev", "build": "next build"},
                    "dependencies": {"next": "15.0.0", "react": "19.0.0", "typescript": "5.0.0"},
                }
            ),
            encoding="utf-8",
        )
        (root / "next.config.js").write_text("module.exports = {}\n", encoding="utf-8")
        (root / "tsconfig.json").write_text('{"compilerOptions":{"paths":{"@/*":["./*"]}}}\n', encoding="utf-8")
        route_dir = root / "app" / "api" / "generate-resume"
        route_dir.mkdir(parents=True)
        (route_dir / "route.ts").write_text(
            "import { generateResume } from '@/lib/ai/resumeAgent';\n\n"
            "export async function POST(req: Request) {\n"
            "  const body = await req.json();\n"
            "  return Response.json(await generateResume(body.prompt));\n"
            "}\n",
            encoding="utf-8",
        )
        agent_dir = root / "lib" / "ai"
        agent_dir.mkdir(parents=True)
        (agent_dir / "resumeAgent.ts").write_text(
            "const OLLAMA_BASE_URL = process.env.OLLAMA_BASE_URL || \"http://localhost:11434\";\n"
            "const OLLAMA_MODEL = process.env.OLLAMA_MODEL || \"llama3\";\n\n"
            "export async function generateResume(prompt: string) {\n"
            "  const response = await fetch(`${OLLAMA_BASE_URL}/api/generate`, {\n"
            "    method: \"POST\",\n"
            "    headers: { \"Content-Type\": \"application/json\" },\n"
            "    body: JSON.stringify({ model: OLLAMA_MODEL, prompt }),\n"
            "  });\n"
            "  if (!response.ok) {\n"
            "    throw new Error(\"Could not connect to Ollama. Make sure Ollama is running at OLLAMA_BASE_URL.\");\n"
            "  }\n"
            "  return response.json();\n"
            "}\n",
            encoding="utf-8",
        )
        return root

    def __exit__(self, exc_type, exc, tb) -> None:
        self._temp.cleanup()


def _ollama_log() -> str:
    return (
        "ready - started server on 0.0.0.0:3000\n"
        "POST /api/generate-resume 500 in 1532ms\n"
        "Error: Could not connect to Ollama. Make sure Ollama is running at OLLAMA_BASE_URL.\n"
        "    at generateResume (lib/ai/resumeAgent.ts:8:11)\n"
        "    at POST (app/api/generate-resume/route.ts:5:31)\n"
    )


def _ok_build() -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["npm", "run", "build"], 0, stdout="build ok\n", stderr="")


def _failed_build() -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["npm", "run", "build"], 1, stdout="", stderr="next build failed\n")


if __name__ == "__main__":
    unittest.main()
