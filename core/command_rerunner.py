from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def success(self) -> bool:
        return self.returncode == 0


def rerun_command(command: str, cwd: Optional[str] = None, timeout: int = 30) -> CommandResult:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        return CommandResult(124, stdout, stderr + "\nGhostFix: rerun timed out.")
    return CommandResult(process.returncode, stdout, stderr)

