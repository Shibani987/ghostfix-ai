"""
Patcher
Applies unified diff patches to source files.
Creates backups before patching.
"""
import shutil
import subprocess
import tempfile
import os
from pathlib import Path
from datetime import datetime


BACKUP_DIR = Path.cwd() / ".ghostfix_backups"


class Patcher:
    def __init__(self, config: dict):
        self.create_backup = config.get("create_backup", True)
        self.backup_dir = BACKUP_DIR

    def apply(self, patch_text: str) -> tuple[bool, str]:
        """
        Apply a unified diff patch.
        Returns (success: bool, message: str)
        """
        if not patch_text or not patch_text.strip():
            return False, "Empty patch"

        # Clean up patch text
        patch_text = self._clean_patch(patch_text)

        # Extract target file(s) from patch header
        target_files = self._extract_targets(patch_text)

        # Backup originals
        if self.create_backup and target_files:
            self._backup(target_files)

        # Try git apply first, then manual fallback
        ok, msg = self._git_apply(patch_text)
        if ok:
            return True, msg

        # Fallback: manual apply
        ok, msg = self._manual_apply(patch_text)
        return ok, msg

    # ------------------------------------------------------------------ #
    def _clean_patch(self, patch: str) -> str:
        """Remove markdown fences if AI wrapped the diff."""
        lines = patch.strip().splitlines()
        # Strip ```diff / ``` wrappers
        cleaned = []
        for line in lines:
            if line.strip().startswith("```"):
                continue
            cleaned.append(line)
        return "\n".join(cleaned) + "\n"

    def _extract_targets(self, patch: str) -> list[str]:
        files = []
        for line in patch.splitlines():
            if line.startswith("+++ "):
                # +++ b/src/foo.py  or  +++ src/foo.py
                path = line[4:].strip()
                if path.startswith("b/"):
                    path = path[2:]
                if path and path != "/dev/null":
                    files.append(path)
        return files

    def _backup(self, file_paths: list[str]):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        for fp in file_paths:
            p = Path(fp)
            if p.exists():
                dest_dir = self.backup_dir / ts
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / p.name
                shutil.copy2(p, dest)

    def _git_apply(self, patch: str) -> tuple[bool, str]:
        """Try `git apply` — works best for proper unified diffs."""
        try:
            result = subprocess.run(
                ["git", "apply", "--whitespace=nowarn", "-"],
                input=patch,
                capture_output=True,
                text=True,
                cwd=str(Path.cwd()),
            )
            if result.returncode == 0:
                return True, "Applied via git apply"
            return False, result.stderr.strip()
        except FileNotFoundError:
            return False, "git not found"
        except Exception as e:
            return False, str(e)

    def _manual_apply(self, patch: str) -> tuple[bool, str]:
        """
        Minimal unified-diff applier for simple patches.
        Handles single-file patches with one hunk.
        """
        try:
            lines = patch.splitlines()
            target_file = None
            hunks: list[dict] = []
            current_hunk = None
            orig_start = None

            for line in lines:
                if line.startswith("+++ "):
                    path = line[4:].strip()
                    if path.startswith("b/"):
                        path = path[2:]
                    target_file = path
                elif line.startswith("@@ "):
                    # @@ -start,count +start,count @@
                    import re
                    m = re.search(r'-(\d+)(?:,\d+)?', line)
                    orig_start = int(m.group(1)) if m else 1
                    current_hunk = {"start": orig_start, "lines": []}
                    hunks.append(current_hunk)
                elif current_hunk is not None:
                    current_hunk["lines"].append(line)

            if not target_file or not hunks:
                return False, "Could not parse patch"

            p = Path(target_file)
            if not p.exists():
                return False, f"Target file not found: {target_file}"

            file_lines = p.read_text(errors="replace").splitlines()
            result_lines = list(file_lines)

            # Apply hunks in reverse order so line numbers stay valid
            offset = 0
            for hunk in hunks:
                start_idx = hunk["start"] - 1 + offset  # 0-based
                new_block = []
                remove_count = 0
                for hl in hunk["lines"]:
                    if hl.startswith("-"):
                        remove_count += 1
                    elif hl.startswith("+"):
                        new_block.append(hl[1:])
                    elif hl.startswith(" "):
                        new_block.append(hl[1:])

                # Count context + removed lines to know how many to replace
                total_orig = sum(
                    1 for hl in hunk["lines"] if hl.startswith("-") or hl.startswith(" ")
                )
                result_lines[start_idx: start_idx + total_orig] = new_block
                offset += len(new_block) - total_orig

            p.write_text("\n".join(result_lines) + "\n")
            return True, f"Applied manually to {target_file}"

        except Exception as e:
            return False, f"Manual apply failed: {e}"
