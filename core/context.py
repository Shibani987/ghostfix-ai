import ast
import re
from pathlib import Path


def extract_context(file_path: str, error_text: str, line_no: int | None = None):
    if not error_text and not line_no:
        return {"snippet": None, "line": None, "symbol": None}

    if line_no is None:
        line_match = re.search(r"line (\d+)", error_text)
        if not line_match:
            return {"snippet": None, "line": None, "symbol": None}
        line_no = int(line_match.group(1))
    if not line_no:
        return {"snippet": None, "line": None, "symbol": None}
    path = Path(file_path)

    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return {"line": line_no, "snippet": None, "symbol": None}

    lines = text.splitlines(keepends=True)
    symbol = _find_enclosing_symbol(text, line_no)

    if symbol:
        start, end, name = symbol
        snippet = _numbered_snippet(lines, start, end)
        return {
            "line": line_no,
            "snippet": snippet,
            "symbol": name,
            "start_line": start,
            "end_line": end,
        }

    start = max(1, line_no - 3)
    end = min(len(lines), line_no + 2)
    return {
        "line": line_no,
        "snippet": _numbered_snippet(lines, start, end),
        "symbol": None,
        "start_line": start,
        "end_line": end,
    }


def _find_enclosing_symbol(text: str, line_no: int):
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None

    best = None
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        start = getattr(node, "lineno", None)
        end = getattr(node, "end_lineno", None)
        if not start or not end:
            continue
        if start <= line_no <= end:
            span = end - start
            if best is None or span < best[1] - best[0]:
                best = (start, end, node.name)
    return best


def _numbered_snippet(lines, start: int, end: int) -> str:
    snippet = ""
    for i in range(start - 1, end):
        if 0 <= i < len(lines):
            snippet += f"{i + 1}: {lines[i]}"
    return snippet
