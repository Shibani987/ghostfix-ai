"""
ProcessWatcher
Spawns the user's command, streams stdout/stderr in real-time,
detects errors and drives the fix pipeline.
"""
import subprocess
import threading
import time
import os
import sys
from typing import Callable

from ghostfix.core.error_parser import ErrorParser, ParsedError
from ghostfix.core.context_builder import ContextBuilder
from ghostfix.core.patcher import Patcher
from ghostfix.ai.router import AIRouter


class ProcessWatcher:
    def __init__(self, command: str, config: dict, fix_enabled: bool, renderer):
        self.command = command
        self.config = config
        self.fix_enabled = fix_enabled
        self.renderer = renderer

        self.error_parser = ErrorParser()
        self.context_builder = ContextBuilder(config=config.get("watch", {}))
        self.patcher = Patcher(config=config.get("fix", {}))
        self.ai = AIRouter(config=config)

        self._error_buffer: list[str] = []
        self._in_traceback = False
        self._process = None
        self._lock = threading.Lock()
        self._last_error_hash: str | None = None
        self._retry_counts: dict[str, int] = {}

    # ------------------------------------------------------------------ #
    def run(self):
        """Main loop: start process, restart on fix if needed."""
        max_retries = self.config.get("fix", {}).get("max_retries", 3)

        while True:
            self._error_buffer = []
            self._in_traceback = False
            exit_code = self._spawn()

            if exit_code == 0:
                self.renderer.print_success("Process exited cleanly.")
                break

            # Non-zero exit — try to fix
            if self.fix_enabled and self._error_buffer:
                raw_error = "\n".join(self._error_buffer)
                fixed = self._handle_error(raw_error)
                if fixed and self.config.get("fix", {}).get("restart_on_fix", True):
                    self.renderer.print_info("Restarting process after fix…\n")
                    time.sleep(1)
                    continue
            break

    # ------------------------------------------------------------------ #
    def _spawn(self) -> int:
        """Spawn command, stream output, collect errors. Returns exit code."""
        shell_cmd = self.command
        self.renderer.print_info(f"Starting process…")

        proc = subprocess.Popen(
            shell_cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # merge stderr → stdout
            text=True,
            bufsize=1,
            env={**os.environ},
        )
        self._process = proc

        for line in proc.stdout:
            line = line.rstrip("\n")
            self.renderer.print_log(line)
            self._feed_line(line)

        proc.wait()
        return proc.returncode

    # ------------------------------------------------------------------ #
    def _feed_line(self, line: str):
        """Feed each line to error accumulator."""
        is_error_line = self.error_parser.is_error_signal(line)

        if is_error_line:
            self._in_traceback = True

        if self._in_traceback:
            self._error_buffer.append(line)

        # Flush buffer if we see a blank line after traceback started
        if self._in_traceback and line.strip() == "" and len(self._error_buffer) > 3:
            # Enough context collected — trigger fix if --fix enabled
            if self.fix_enabled:
                raw = "\n".join(self._error_buffer)
                # Run in thread so log streaming continues
                t = threading.Thread(target=self._handle_error, args=(raw,), daemon=True)
                t.start()
            self._in_traceback = False
            self._error_buffer = []

    # ------------------------------------------------------------------ #
    def _handle_error(self, raw_error: str) -> bool:
        """Full fix pipeline. Returns True if patch was applied."""
        import hashlib
        err_hash = hashlib.md5(raw_error[:300].encode()).hexdigest()

        # Dedup — don't fix same error repeatedly
        count = self._retry_counts.get(err_hash, 0)
        max_r = self.config.get("fix", {}).get("max_retries", 3)
        if count >= max_r:
            self.renderer.print_warning(f"Same error seen {count}x — skipping auto-fix.")
            return False
        self._retry_counts[err_hash] = count + 1

        # 1. Parse error
        self.renderer.print_step("🔍 Parsing error…")
        parsed: ParsedError = self.error_parser.parse(raw_error)
        self.renderer.show_error_summary(parsed)

        # 2. Build codebase context
        self.renderer.print_step("📂 Searching codebase…")
        context = self.context_builder.build(parsed)

        # 3. Ask AI
        self.renderer.print_step("🤖 Asking AI for fix…")
        try:
            ai_result = self.ai.analyze(parsed=parsed, context=context)
        except Exception as e:
            self.renderer.print_error(f"AI error: {e}")
            return False

        if not ai_result:
            self.renderer.print_warning("AI could not produce a fix.")
            return False

        # 4. Show result
        self.renderer.show_ai_result(ai_result)

        # 5. Confirm + apply patch
        if not ai_result.get("patch"):
            self.renderer.print_info("No patch generated.")
            return False

        auto = self.config.get("fix", {}).get("auto_apply", False)
        if not auto:
            from rich.prompt import Prompt
            choice = Prompt.ask(
                "\n[bold]Apply patch?[/bold]",
                choices=["y", "n", "e", "s"],
                default="n",
            )
            if choice == "n":
                return False
            if choice == "s":
                self.renderer.show_full_context(context)
                return False
            if choice == "e":
                ai_result["patch"] = self._open_editor(ai_result["patch"])

        # Apply
        self.renderer.print_step("🔧 Applying patch…")
        success, msg = self.patcher.apply(ai_result["patch"])
        if success:
            self.renderer.print_success(f"Patch applied! {msg}")
            return True
        else:
            self.renderer.print_error(f"Patch failed: {msg}")
            return False

    def _open_editor(self, patch: str) -> str:
        """Open patch in $EDITOR for manual editing."""
        import tempfile
        editor = os.environ.get("EDITOR", "nano")
        with tempfile.NamedTemporaryFile(suffix=".diff", mode="w", delete=False) as f:
            f.write(patch)
            tmp = f.name
        os.system(f"{editor} {tmp}")
        return open(tmp).read()
