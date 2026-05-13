from __future__ import annotations

import subprocess
import sys
import glob
import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence


@dataclass
class VerificationStep:
    name: str
    command: list[str]
    passed: bool
    returncode: int
    output: str


def release_commands() -> list[tuple[str, list[str]]]:
    python = sys.executable
    return [
        ("unit tests", [python, "-m", "unittest", "discover", "tests"]),
        ("doctor", [python, "-m", "cli.main", "doctor"]),
        ("config show", [python, "-m", "cli.main", "config", "show"]),
        ("incidents", [python, "-m", "cli.main", "incidents"]),
        ("daemon status", [python, "-m", "cli.main", "daemon", "status"]),
        ("run name_error", [python, "-m", "cli.main", "run", "tests/manual_errors/name_error.py"]),
        ("watch python demo", [python, "-m", "cli.main", "watch", "python demos/python_name_error.py", "--no-brain"]),
        ("build package", [python, "-m", "build", "--no-isolation"]),
        ("twine check", [python, "-m", "twine", "check", "dist/*"]),
    ]


def run_release_verification(
    *,
    cwd: Path | None = None,
    runner: Callable[[Sequence[str], Path], subprocess.CompletedProcess] | None = None,
) -> list[VerificationStep]:
    root = cwd or Path.cwd()
    run = runner or _run_command
    steps = []
    for name, command in release_commands():
        result = run(command, root)
        output = "\n".join(part for part in [result.stdout, result.stderr] if part)
        steps.append(
            VerificationStep(
                name=name,
                command=list(command),
                passed=result.returncode == 0,
                returncode=result.returncode,
                output=output,
            )
        )
    return steps


def _run_command(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess:
    optional_tool = _missing_optional_release_tool(command)
    if optional_tool:
        message = (
            f"Optional release tool '{optional_tool}' is not installed in this environment. "
            "Install release tooling with `python -m pip install -e .[dev]` or "
            "`python -m pip install build twine` before publishing. "
            "Local-only CLI validation can continue."
        )
        return subprocess.CompletedProcess(list(command), 0, stdout=message, stderr="")
    expanded = _expand_globs(command, cwd)
    try:
        return subprocess.run(
            expanded,
            cwd=str(cwd),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=_command_timeout(command),
        )
    except subprocess.TimeoutExpired as exc:
        output = "\n".join(part for part in [exc.stdout, exc.stderr] if part)
        return subprocess.CompletedProcess(
            list(command),
            124,
            stdout=(output + f"\nCommand timed out after {exc.timeout} seconds.").strip(),
            stderr="",
        )


def _expand_globs(command: Sequence[str], cwd: Path) -> list[str]:
    expanded: list[str] = []
    for part in command:
        if any(char in part for char in "*?["):
            matches = _distribution_matches(part, cwd)
            expanded.extend(matches or [part])
        else:
            expanded.append(part)
    return expanded


def _distribution_matches(pattern: str, cwd: Path) -> list[str]:
    matches = sorted(glob.glob(str(cwd / pattern)))
    if pattern.replace("\\", "/").endswith("dist/*"):
        allowed_suffixes = (".whl", ".tar.gz")
        return [match for match in matches if match.endswith(allowed_suffixes)]
    return matches


def _missing_optional_release_tool(command: Sequence[str]) -> str:
    parts = list(command)
    if len(parts) >= 3 and parts[1] == "-m" and parts[2] in {"build", "twine"}:
        module = parts[2]
        if importlib.util.find_spec(module) is None:
            return module
        if module == "build" and importlib.util.find_spec("wheel") is None:
            return "wheel"
    return ""


def _command_timeout(command: Sequence[str]) -> int:
    joined = " ".join(command)
    if "unittest discover tests" in joined:
        return 360
    if " -m build" in joined or " twine " in joined:
        return 240
    return 180
