from core.memory import save_memory
from core.training_memory import save_training_data


def _verbose_logging(parsed_error) -> bool:
    return bool(isinstance(parsed_error, dict) and parsed_error.get("verbose"))


def log_error(parsed_error, result, context=None):
    if not parsed_error or result["status"] == "success":
        return

    # ❌ Skip bad fallback data
    if result.get("source") == "fallback":
        return

    # ❌ Skip useless errors
    if "Unhandled error" in str(result.get("cause")):
        return

    snippet = context.get("snippet") if isinstance(context, dict) else None

    data = {
        "error": parsed_error["raw"],
        "error_type": parsed_error["type"],
        "message": parsed_error["message"],
        "file": parsed_error.get("file"),
        "line": parsed_error.get("line"),
        "cause": result["cause"],
        "fix": result["fix"],
        "source": result.get("source", "unknown"),
        "context": snippet,
        "language": "python",
        "success": True,
    }

    # ✅ 1. Save to memory (fast lookup)
    try:
        save_memory(
            parsed_error["type"],
            parsed_error["message"],
            result["cause"],
            result["fix"],
            context=snippet,
            language="python",
            success=True,
            source=result.get("source", "unknown"),
        )
    except Exception as e:
        if _verbose_logging(parsed_error):
            print(f"Memory save failed: {str(e)[:100]}")

    # ✅ 2. Save to training dataset (SELF LEARNING 🔥)
    try:
        training_data = {
            "error": parsed_error["raw"],
            "error_type": parsed_error["type"],
            "message": parsed_error["message"],
            "cause": result["cause"],
            "fix": result["fix"],
            "context": snippet,
            "language": "python",
            "source": "real_user",   # 🔥 IMPORTANT
            "success": True,
        }

        save_training_data(training_data)

    except Exception as e:
        if _verbose_logging(parsed_error):
            print(f"Training save failed: {str(e)[:100]}")
