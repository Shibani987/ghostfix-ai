import re

def detect_error(stderr: str):
    if not stderr:
        return {
            "status": "success",
            "error": None,
            "line": None
        }

    # 🔍 extract line number
    line_match = re.search(r"line (\d+)", stderr)
    line = line_match.group(1) if line_match else "unknown"

    # 🔥 ModuleNotFoundError (SMART)
    match = re.search(r"No module named '(.+?)'", stderr)
    if match:
        package = match.group(1)

        return {
            "status": "error",
            "type": "dependency",
            "error": stderr,
            "line": line,
            "cause": f"Missing Python package: {package}",
            "fix": f"pip install {package}"
        }

    # 🔥 SyntaxError
    if "SyntaxError" in stderr:
        return {
            "status": "error",
            "type": "syntax",
            "error": stderr,
            "line": line,
            "cause": "Syntax issue in code",
            "fix": "Check the syntax near the mentioned line"
        }

    # 🔥 NameError
    if "NameError" in stderr:
        return {
            "status": "error",
            "type": "name",
            "error": stderr,
            "line": line,
            "cause": "Undefined variable used",
            "fix": "Check variable name or define it before use"
        }

    # 🔥 TypeError
    if "TypeError" in stderr:
        return {
            "status": "error",
            "type": "type",
            "error": stderr,
            "line": line,
            "cause": "Invalid data type usage",
            "fix": "Check function arguments or variable types"
        }

    # 🔥 File not found
    if "No such file or directory" in stderr or "can't open file" in stderr:
        return {
            "status": "error",
            "type": "file",
            "error": stderr,
            "line": line,
            "cause": "File not found",
            "fix": "Check file path or current directory"
        }

    # 🔥 Unknown error (IMPROVED)
    last_line = stderr.strip().split("\n")[-1]

    return {
        "status": "error",
        "type": "unknown",
        "error": stderr,
        "line": line,
        "cause": f"Unknown error: {last_line}",
        "fix": "Check traceback above"
    }