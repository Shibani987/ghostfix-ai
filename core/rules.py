from core.decision_engine import decide_fix


def apply_rules(error, context=None):
    """Backward-compatible wrapper for older callers."""
    decision = decide_fix(error, context)
    return {
        "status": decision.status,
        "cause": decision.cause,
        "fix": decision.fix,
        "source": decision.source,
        "confidence": decision.confidence,
        "auto_fix_available": decision.auto_fix_available,
        "auto_fix_plan": decision.auto_fix_plan,
    }
