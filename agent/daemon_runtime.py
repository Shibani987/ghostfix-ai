from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from agent.terminal_watcher import watch_command


DAEMON_DIR = ".ghostfix"
STATE_FILE = "daemon.json"
STOP_FILE = "daemon.stop"


def daemon_dir(root: Optional[Path] = None) -> Path:
    return (root or Path.cwd()) / DAEMON_DIR


def daemon_state_path(root: Optional[Path] = None) -> Path:
    return daemon_dir(root) / STATE_FILE


def daemon_stop_path(root: Optional[Path] = None) -> Path:
    return daemon_dir(root) / STOP_FILE


def read_daemon_status(root: Optional[Path] = None) -> dict:
    path = daemon_state_path(root)
    if not path.exists():
        return {"status": "stopped"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"status": "unknown", "state_file": str(path)}
    data.setdefault("status", "unknown")
    data["state_file"] = str(path)
    return data


def request_daemon_stop(root: Optional[Path] = None) -> Path:
    path = daemon_stop_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(datetime.now().isoformat(timespec="seconds"), encoding="utf-8")
    return path


def start_daemon(
    command: str,
    *,
    cwd: Optional[str] = None,
    auto_fix: bool = False,
    verbose: bool = False,
    restart_delay: float = 1.0,
    max_runs: Optional[int] = None,
) -> int:
    """Run a foreground daemon loop around watch mode."""
    root = Path(cwd) if cwd else Path.cwd()
    daemon_dir(root).mkdir(parents=True, exist_ok=True)
    stop_path = daemon_stop_path(root)
    if stop_path.exists():
        stop_path.unlink()

    _write_state(root, status="running", command=command, runs=0)
    runs = 0
    interrupted = False
    last_returncode = 0

    try:
        while not stop_path.exists():
            runs += 1
            _write_state(root, status="running", command=command, runs=runs)
            result = watch_command(command, cwd=str(root), auto_fix=auto_fix, verbose=verbose)
            last_returncode = result.returncode if result.returncode is not None else 0

            if max_runs is not None and runs >= max_runs:
                break
            if stop_path.exists():
                break
            time.sleep(max(0.0, restart_delay))
    except KeyboardInterrupt:
        interrupted = True
    finally:
        if stop_path.exists():
            stop_path.unlink()
        _write_state(
            root,
            status="stopped",
            command=command,
            runs=runs,
            stopped_at=datetime.now().isoformat(timespec="seconds"),
            interrupted=interrupted,
            last_returncode=last_returncode,
        )

    return last_returncode


def _write_state(root: Path, **data) -> None:
    path = daemon_state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "pid": os.getpid(),
        "cwd": str(root),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        **data,
    }
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")
