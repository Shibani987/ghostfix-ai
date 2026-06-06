"""
ContextBuilder
Given a ParsedError, finds relevant source files and extracts
surrounding code context to send to the AI.
"""
import os
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class CodeContext:
    primary_file: str | None = None
    primary_snippet: str = ""
    related_files: list[dict] = field(default_factory=list)
    project_tree: str = ""


DEFAULT_IGNORE = {
    "node_modules", ".git", "dist", "__pycache__", "venv",
    ".venv", "env", ".env", "migrations", ".mypy_cache",
    ".pytest_cache", "build", "target", ".idea", ".vscode",
    "coverage", ".next", ".nuxt", "out",
}

MAX_FILE_SIZE_BYTES = 500 * 1024  # 500 KB


class ContextBuilder:
    def __init__(self, config: dict):
        self.ignore = set(config.get("ignore", [])) | DEFAULT_IGNORE
        self.context_lines = config.get("context_lines", 60)
        self.max_file_size = config.get("max_file_size_kb", 500) * 1024
        self.root = Path.cwd()

    # ------------------------------------------------------------------ #
    def build(self, parsed) -> CodeContext:
        ctx = CodeContext()
        ctx.project_tree = self._build_tree(self.root, max_depth=3)

        # Primary file
        if parsed.file_path:
            full_path = self._resolve(parsed.file_path)
            if full_path and full_path.exists():
                ctx.primary_file = str(full_path)
                ctx.primary_snippet = self._extract_snippet(
                    full_path, parsed.line_number, self.context_lines
                )

        # Related files from stack trace
        seen = {ctx.primary_file}
        for fp, ln in (parsed.all_files or []):
            full_path = self._resolve(fp)
            if full_path and full_path.exists() and str(full_path) not in seen:
                seen.add(str(full_path))
                snippet = self._extract_snippet(full_path, ln, 30)
                ctx.related_files.append({
                    "path": str(full_path),
                    "line": ln,
                    "snippet": snippet,
                })
                if len(ctx.related_files) >= 4:
                    break

        return ctx

    # ------------------------------------------------------------------ #
    def _resolve(self, file_path: str) -> Path | None:
        """Try to resolve a relative or partial path from cwd."""
        p = Path(file_path)
        if p.is_absolute() and p.exists():
            return p
        # Relative to cwd
        candidate = self.root / p
        if candidate.exists():
            return candidate
        # Search recursively
        name = p.name
        for found in self.root.rglob(name):
            if not self._is_ignored(found):
                return found
        return None

    def _is_ignored(self, path: Path) -> bool:
        return any(part in self.ignore for part in path.parts)

    def _extract_snippet(self, path: Path, center_line: int | None, n_lines: int) -> str:
        try:
            if path.stat().st_size > self.max_file_size:
                return f"[File too large: {path}]"
            lines = path.read_text(errors="replace").splitlines()
            if center_line is None:
                # Return first n_lines
                snippet_lines = lines[:n_lines]
                start = 1
            else:
                half = n_lines // 2
                start = max(0, center_line - half - 1)
                end = min(len(lines), center_line + half)
                snippet_lines = lines[start:end]

            numbered = []
            for i, l in enumerate(snippet_lines, start=start + 1):
                marker = ">>>" if i == center_line else "   "
                numbered.append(f"{marker} {i:4d} | {l}")
            return "\n".join(numbered)
        except Exception as e:
            return f"[Could not read {path}: {e}]"

    def _build_tree(self, root: Path, max_depth: int = 3, _depth: int = 0) -> str:
        if _depth > max_depth:
            return ""
        lines = []
        try:
            entries = sorted(root.iterdir(), key=lambda p: (p.is_file(), p.name))
        except PermissionError:
            return ""

        for entry in entries:
            if entry.name.startswith(".") or entry.name in self.ignore:
                continue
            indent = "  " * _depth
            if entry.is_dir():
                lines.append(f"{indent}📁 {entry.name}/")
                lines.append(self._build_tree(entry, max_depth, _depth + 1))
            else:
                lines.append(f"{indent}📄 {entry.name}")

        return "\n".join(filter(None, lines))
