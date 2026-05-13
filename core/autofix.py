import difflib
import ast
import re
import py_compile
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


SAFE_AUTOFIX_TYPES = {"JSONDecodeError", "SyntaxError", "IndentationError"}
UNSAFE_AUTOFIX_TYPES = {"NameError", "FileNotFoundError", "KeyError", "IndexError"}


@dataclass
class PatchPlan:
    available: bool
    reason: str
    replacement: str = ""
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    preview: str = ""
    fix_kind: str = "model_suggested_fix"
    validation: str = ""
    changed_line_count: int = 0
    deterministic_validator_result: str = ""
    compile_validation_result: str = ""


def create_backup(file_path: str):
    path = Path(file_path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = path.with_suffix(path.suffix + f".bak_{timestamp}")
    backup_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return backup_path


def build_patch_plan(file_path: str, parsed_error: dict, decision: Optional[dict] = None) -> PatchPlan:
    if not parsed_error:
        return PatchPlan(False, "No parsed error")

    error_type = parsed_error.get("type")
    if error_type in UNSAFE_AUTOFIX_TYPES:
        return PatchPlan(False, f"Auto-fix is disabled for {error_type}")

    if error_type not in SAFE_AUTOFIX_TYPES:
        return PatchPlan(False, f"No safe autofix available for {error_type}")

    line_no = parsed_error.get("line")
    if not line_no:
        return PatchPlan(False, "No line number found")

    path = Path(file_path)
    if not path.exists():
        return PatchPlan(False, "File not found")

    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)

    if error_type == "JSONDecodeError":
        plan = _json_loads_empty_guard(lines, line_no)
    elif error_type in {"SyntaxError", "IndentationError"}:
        plan = _simple_syntax_fix(lines, line_no, parsed_error)
    else:
        plan = PatchPlan(False, f"No safe autofix available for {error_type}")

    if not plan.available:
        return plan

    validation = _validate_deterministic_patch(path, lines, plan)
    if validation:
        return PatchPlan(False, validation)

    new_lines = _apply_plan_to_lines(lines, plan)
    plan.preview = _diff_preview(path, lines, new_lines)
    plan.changed_line_count = max(0, plan.end_line - plan.start_line + 1)
    if error_type in {"SyntaxError", "IndentationError"}:
        plan.fix_kind = "deterministic_verified_fix"
        plan.validation = "ast.parse + compile passed"
        plan.deterministic_validator_result = "passed"
        plan.compile_validation_result = "passed"
    return plan


def apply_patch_plan(file_path: str, plan: PatchPlan):
    if not plan.available:
        return {"applied": False, "reason": plan.reason}

    path = Path(file_path)
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    sandbox_error = _sandbox_validate_patch(path, lines, plan)
    if sandbox_error:
        return {
            "applied": False,
            "reason": sandbox_error,
            "rollback_metadata": {"sandbox_validated": False, "target": str(path)},
        }
    backup_path = create_backup(file_path)

    lines[plan.start_line - 1:plan.end_line] = plan.replacement.splitlines(keepends=True)
    path.write_text("".join(lines), encoding="utf-8")

    return {
        "applied": True,
        "backup": str(backup_path),
        "message": "Safe auto-fix applied",
        "patch": plan.preview,
        "rollback_metadata": {
            "backup": str(backup_path),
            "restored_original": False,
            "sandbox_validated": True,
            "target": str(path),
        },
    }


def apply_autofix(file_path: str, parsed_error: dict, result: dict):
    plan = build_patch_plan(file_path, parsed_error, result)
    return apply_patch_plan(file_path, plan)


def _json_loads_empty_guard(lines, line_no: int) -> PatchPlan:
    index = line_no - 1
    if index < 0 or index >= len(lines):
        return PatchPlan(False, "Line number is outside the file")

    line = lines[index]
    match = re.search(r"(.+?)=\s*json\.loads\((.+?)\)", line)
    if not match:
        return PatchPlan(False, "JSONDecodeError is not on a simple json.loads assignment")

    left_side = match.group(1).strip()
    variable = match.group(2).strip()
    indent = line[:len(line) - len(line.lstrip())]

    replacement = "".join([
        f"{indent}if {variable}:\n",
        f"{indent}    {left_side} = json.loads({variable})\n",
        f"{indent}else:\n",
        f"{indent}    {left_side} = None\n",
        f'{indent}    print("GhostFix: Empty JSON input")\n',
    ])

    return PatchPlan(
        available=True,
        reason="Safe json.loads empty-input guard can be applied",
        replacement=replacement,
        start_line=line_no,
        end_line=line_no,
    )


def _simple_syntax_fix(lines, line_no: int, parsed_error: dict) -> PatchPlan:
    index = line_no - 1
    if index < 0 or index >= len(lines):
        return PatchPlan(False, "Line number is outside the file")

    line = lines[index]
    stripped = line.rstrip("\r\n")
    ending = _line_ending(line)
    missing_colon_keywords = ("if ", "elif ", "else", "for ", "while ", "def ", "class ", "try", "except", "finally", "with ")

    if stripped.strip().startswith(missing_colon_keywords) and not stripped.rstrip().endswith(":"):
        replacement = stripped.rstrip() + ":" + ending
        return PatchPlan(
            available=True,
            reason="Safe missing-colon syntax fix can be applied",
            replacement=replacement,
            start_line=line_no,
            end_line=line_no,
        )

    parenthesis_plan = _missing_closing_parenthesis(lines, line_no)
    if parenthesis_plan.available:
        return parenthesis_plan

    indentation_plan = _simple_indentation_fix(lines, line_no, parsed_error)
    if indentation_plan.available:
        return indentation_plan

    comma_plan = _simple_duplicate_comma_fix(lines, line_no)
    if comma_plan.available:
        return comma_plan

    return PatchPlan(False, "No deterministic simple syntax patch found; manual review required")


def _missing_closing_parenthesis(lines, line_no: int) -> PatchPlan:
    line = lines[line_no - 1]
    stripped = line.rstrip("\r\n")
    ending = _line_ending(line)
    if stripped.count("(") - stripped.count(")") != 1:
        return PatchPlan(False, "No deterministic missing parenthesis patch found")
    if stripped.count("[") != stripped.count("]") or stripped.count("{") != stripped.count("}"):
        return PatchPlan(False, "Mixed delimiter imbalance requires manual review")
    return PatchPlan(
        available=True,
        reason="Safe missing closing parenthesis syntax fix can be applied",
        replacement=stripped.rstrip() + ")" + ending,
        start_line=line_no,
        end_line=line_no,
    )


def _simple_indentation_fix(lines, line_no: int, parsed_error: dict) -> PatchPlan:
    line = lines[line_no - 1]
    stripped = line.lstrip(" \t")
    if not stripped:
        return PatchPlan(False, "No deterministic indentation patch found")

    message = (parsed_error.get("message") or "").lower()
    ending = _line_ending(line)

    if "unexpected indent" in message and line != stripped:
        return PatchPlan(
            available=True,
            reason="Safe unexpected-indent repair can be applied",
            replacement=stripped.rstrip("\r\n") + ending,
            start_line=line_no,
            end_line=line_no,
        )

    candidate_indents = _candidate_indents(lines, line_no)
    viable_plans = []
    stripped_body = stripped.rstrip("\r\n")
    for indent in candidate_indents:
        replacement = f"{indent}{stripped_body}{ending}"
        plan = PatchPlan(
            available=True,
            reason="Safe indentation mismatch repair can be applied",
            replacement=replacement,
            start_line=line_no,
            end_line=line_no,
        )
        new_lines = _apply_plan_to_lines(lines, plan)
        try:
            ast.parse("".join(new_lines))
            compile("".join(new_lines), "<ghostfix-autofix>", "exec")
        except SyntaxError:
            continue
        viable_plans.append(plan)

    if len(viable_plans) == 1:
        return viable_plans[0]
    return PatchPlan(False, "Indentation repair is ambiguous and requires manual review")


def _simple_duplicate_comma_fix(lines, line_no: int) -> PatchPlan:
    line = lines[line_no - 1]
    if line.count(",,") != 1:
        return PatchPlan(False, "No deterministic trailing comma patch found")
    if not any(token in line for token in ("[", "]", "{", "}", "(", ")")):
        return PatchPlan(False, "Duplicate comma is not inside a simple literal")
    replacement = line.replace(",,", ",", 1)
    return PatchPlan(
        available=True,
        reason="Safe duplicate-comma literal syntax fix can be applied",
        replacement=replacement,
        start_line=line_no,
        end_line=line_no,
    )


def _validate_deterministic_patch(path: Path, old_lines: list[str], plan: PatchPlan) -> str:
    if plan.start_line is None or plan.end_line is None:
        return "Patch does not identify an exact line range"
    if plan.start_line < 1 or plan.end_line > len(old_lines):
        return "Patch line range is outside the file"

    new_lines = _apply_plan_to_lines(old_lines, plan)
    prefix = old_lines[:plan.start_line - 1]
    suffix = old_lines[plan.end_line:]
    new_suffix_start = len(new_lines) - len(suffix)
    if new_lines[:len(prefix)] != prefix or new_lines[new_suffix_start:] != suffix:
        return "Patch changes unrelated lines and requires manual review"

    source = "".join(new_lines)
    try:
        ast.parse(source, filename=str(path))
        compile(source, str(path), "exec")
    except SyntaxError as exc:
        return f"Generated patch is not valid Python: {exc.msg}"
    return ""


def _sandbox_validate_patch(path: Path, old_lines: list[str], plan: PatchPlan) -> str:
    validation = _validate_deterministic_patch(path, old_lines, plan)
    if validation:
        return validation
    new_lines = _apply_plan_to_lines(old_lines, plan)
    with tempfile.TemporaryDirectory(prefix="ghostfix_autofix_") as temp_dir:
        sandbox_path = Path(temp_dir) / path.name
        sandbox_path.write_text("".join(new_lines), encoding="utf-8")
        try:
            py_compile.compile(str(sandbox_path), doraise=True)
        except py_compile.PyCompileError as exc:
            return f"Sandbox compile failed: {exc.msg}"
    return ""


def _apply_plan_to_lines(lines: list[str], plan: PatchPlan) -> list[str]:
    new_lines = lines[:]
    new_lines[plan.start_line - 1:plan.end_line] = plan.replacement.splitlines(keepends=True)
    return new_lines


def _candidate_indents(lines: list[str], line_no: int) -> list[str]:
    indents = []
    for line in lines:
        if line.strip():
            indent = line[:len(line) - len(line.lstrip(" \t"))]
            if indent not in indents:
                indents.append(indent)
    previous = _previous_nonblank_line(lines, line_no)
    if previous:
        prev_indent = previous[:len(previous) - len(previous.lstrip(" \t"))]
        block_indent = prev_indent + "    "
        if block_indent not in indents:
            indents.append(block_indent)
    return indents


def _previous_nonblank_line(lines: list[str], line_no: int) -> str:
    for candidate in reversed(lines[:line_no - 1]):
        if candidate.strip():
            return candidate
    return ""


def _line_ending(line: str) -> str:
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    return ""




def _diff_preview(path: Path, old_lines, new_lines) -> str:
    old_preview_lines = _ensure_preview_newlines(old_lines)
    new_preview_lines = _ensure_preview_newlines(new_lines)
    return "".join(
        difflib.unified_diff(
            old_preview_lines,
            new_preview_lines,
            fromfile=str(path),
            tofile=str(path),
            lineterm="\n",
        )
    )


def _ensure_preview_newlines(lines) -> list[str]:
    return [line if line.endswith("\n") else f"{line}\n" for line in lines]
