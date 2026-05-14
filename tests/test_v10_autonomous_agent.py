from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.autonomous_agent import AutonomousDebuggingAgent, repair_autonomously
from core.autonomous_benchmark import AutonomousBenchmarkReport, run_autonomous_benchmark
from core.iterative_agent import IterativeValidationResult
from core.repo_engine import build_repo_snapshot


class AutonomousAgentV10Tests(unittest.TestCase):
    def test_repo_graph_indexes_components_and_entrypoints(self):
        with _ts_project() as root:
            app = root / "src" / "main.tsx"
            app.write_text("import React from 'react'\ncreateRoot(root).render(<App />)\nexport default function App() { return null }\n", encoding="utf-8")
            snapshot = build_repo_snapshot(root)

        self.assertIn("App", snapshot.graph.components["src/main.tsx"])
        self.assertIn("react-dom", snapshot.graph.entrypoints["src/main.tsx"])
        self.assertIn("components=", snapshot.summary())

    def test_autonomous_agent_ranks_validated_candidate(self):
        with _ts_project() as root:
            app = root / "src" / "app.ts"
            helper = root / "src" / "helper.ts"
            app.write_text("import { helper } from './helper'\nconst value = 1\nconsole.log(helper, value)\n", encoding="utf-8")
            helper.write_text("export const helper = 1;\n", encoding="utf-8")
            diagnostic = _diag(app)
            diagnostic["patch_block"] = _line_patch(app, 2, "const value = 1;\n")
            final_block = _framework_block(app, "import { helper } from './helper.ts'\nconst value = 1;\nconsole.log(helper, value)\n")
            with patch(
                "core.autonomous_agent.iterative_validate_patch",
                side_effect=[
                    IterativeValidationResult(False, "candidate regressed", regression_detected=True, confidence=30),
                    IterativeValidationResult(True, "candidate passed", patch_block=final_block, confidence=92),
                ],
            ) as mocked:
                result = AutonomousDebuggingAgent(cwd=root, command="npm run build").repair(diagnostic)

        self.assertTrue(result.ok, result.reason)
        self.assertEqual(mocked.call_args.kwargs["max_retries"], 3)
        self.assertEqual(result.telemetry["convergence_result"], "converged")
        self.assertEqual(result.telemetry["regression_result"], "passed")
        self.assertGreaterEqual(result.telemetry["final_confidence"], 90)
        self.assertEqual(result.telemetry["candidate_ranking"][0]["validation_success"], True)
        self.assertIn("helper.ts", result.patch_block["patch"])

    def test_autonomous_agent_blocks_sensitive_cases(self):
        with _ts_project() as root:
            auth = root / "src" / "auth" / "login.ts"
            auth.parent.mkdir()
            auth.write_text("export const login = true\n", encoding="utf-8")
            result = repair_autonomously(
                {
                    "language": "typescript",
                    "framework": "next.js",
                    "file": str(auth),
                    "root_cause": "auth_session_failure",
                    "message": "login failed",
                    "confidence": 90,
                },
                cwd=root,
                command="npm run build",
            )

        self.assertFalse(result.ok)
        self.assertIn("blocked", result.reason.lower())

    def test_autonomous_agent_requires_rollback_capable_validation(self):
        with _ts_project() as root:
            app = root / "src" / "app.ts"
            app.write_text("const value = 1\n", encoding="utf-8")
            diagnostic = _diag(app)
            diagnostic["patch_block"] = _line_patch(app, 1, "const value = 1;\n")
            bad_validated = dict(diagnostic["patch_block"])
            with patch("core.autonomous_agent.iterative_validate_patch", return_value=IterativeValidationResult(True, "passed", patch_block=bad_validated, confidence=90)):
                result = repair_autonomously(diagnostic, cwd=root, command="npm run build")

        self.assertFalse(result.ok)
        self.assertIn("rollback", result.reason.lower())

    def test_benchmark_reports_required_rates(self):
        report = AutonomousBenchmarkReport(
            total_cases=4,
            solved_cases=3,
            regressed_cases=1,
            validation_successes=3,
            retry_successes=2,
            unresolved_cases=1,
            elapsed_ms=10,
        )
        payload = report.to_dict()

        self.assertEqual(payload["solve_rate"], 0.75)
        self.assertEqual(payload["regression_rate"], 0.25)
        self.assertEqual(payload["validation_success_rate"], 0.75)
        self.assertEqual(payload["retry_success_rate"], 0.5)
        self.assertEqual(payload["unresolved_rate"], 0.25)

    def test_benchmark_runs_cases_through_agent_api(self):
        with patch(
            "core.autonomous_benchmark.repair_autonomously",
            side_effect=[
                _fake_result(True, retry_count=1),
                _fake_result(False, regression="failed"),
            ],
        ):
            report = run_autonomous_benchmark([{"diagnostic": {"framework": "next.js"}}, {"diagnostic": {"framework": "react"}}])

        self.assertEqual(report.solved_cases, 1)
        self.assertEqual(report.unresolved_cases, 1)
        self.assertEqual(report.retry_successes, 1)
        self.assertEqual(report.regressed_cases, 1)


class _FakeResult:
    def __init__(self, ok: bool, telemetry: dict):
        self.ok = ok
        self.telemetry = telemetry


def _fake_result(ok: bool, *, retry_count: int = 0, regression: str = "passed") -> _FakeResult:
    return _FakeResult(ok, {"retry_count": retry_count, "regression_result": regression, "convergence_result": "converged" if ok else "unresolved"})


class _ts_project:
    def __enter__(self) -> Path:
        self._temp = tempfile.TemporaryDirectory()
        root = Path(self._temp.name)
        (root / "package.json").write_text(json.dumps({"scripts": {"build": "tsc --noEmit"}, "dependencies": {"typescript": "5.0.0", "next": "15.0.0", "react": "19.0.0"}}), encoding="utf-8")
        (root / "tsconfig.json").write_text("{}", encoding="utf-8")
        (root / "src").mkdir()
        return root

    def __exit__(self, exc_type, exc, tb) -> None:
        self._temp.cleanup()


def _diag(path: Path) -> dict:
    return {
        "language": "typescript",
        "framework": "next.js",
        "file": str(path),
        "error_type": "ModuleNotFound",
        "root_cause": "next_module_not_found",
        "message": "Cannot find module './helper'",
        "confidence": 85,
    }


def _line_patch(path: Path, line: int, replacement: str) -> dict:
    old_lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    new_lines = old_lines[:]
    new_lines[line - 1:line] = [replacement]
    import difflib

    return {
        "available": True,
        "file_path": str(path),
        "start_line": line,
        "end_line": line,
        "replacement": replacement,
        "patch": "".join(difflib.unified_diff(old_lines, new_lines, fromfile=str(path), tofile=str(path), lineterm="\n")),
        "language": "javascript/typescript",
        "framework": "next.js",
    }


def _framework_block(path: Path, new_text: str) -> dict:
    old_text = path.read_text(encoding="utf-8")
    return {
        "available": True,
        "action": "framework_multi_file",
        "reason": "validated",
        "file_path": str(path),
        "files": [{"file_path": str(path), "old_text": old_text, "new_text": new_text, "reason": "test"}],
        "patch": new_text,
        "validation_commands": [["npm", "run", "build"]],
        "language": "javascript/typescript",
        "framework": "next.js",
        "requires_project_validation": True,
    }


def _ok() -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["validation"], 0, stdout="ok\n", stderr="")


if __name__ == "__main__":
    unittest.main()
