from __future__ import annotations

import unittest
from unittest.mock import patch

from core.decision_engine import decide_fix
from core.language_diagnostics import diagnose_non_python
from ml import retriever_router


class RetrieverRouterTests(unittest.TestCase):
    def test_router_falls_back_when_embedding_unavailable(self):
        with patch("ml.embedding_retriever.predict_fix", side_effect=RuntimeError("missing")), patch(
            "ml.predict_fix.predict_fix",
            return_value=[
                {
                    "confidence": 71,
                    "cause": "TF-IDF cause",
                    "fix": "TF-IDF fix",
                    "error_type": "NameError",
                }
            ],
        ):
            results = retriever_router.predict_fix("NameError: name 'x' is not defined", top_k=1)

        self.assertEqual(results[0]["cause"], "TF-IDF cause")
        self.assertEqual(results[0]["retriever_backend"], "tfidf_retriever")

    def test_router_returns_tfidf_result_when_embedding_returns_empty(self):
        with patch("ml.embedding_retriever.predict_fix", return_value=[]), patch(
            "ml.predict_fix.predict_fix",
            return_value=[
                {
                    "confidence": 72,
                    "cause": "TF-IDF fallback cause",
                    "fix": "TF-IDF fallback fix",
                    "error_type": "TypeError",
                }
            ],
        ):
            results = retriever_router.predict_fix("TypeError: bad operand", top_k=1)

        self.assertEqual(results[0]["fix"], "TF-IDF fallback fix")
        self.assertEqual(results[0]["retriever_backend"], "tfidf_retriever")

    def test_rules_win_over_low_confidence_retriever(self):
        with patch.dict("os.environ", {}, clear=True), patch("core.decision_engine.search_memory", return_value=None), patch(
            "ml.retriever_router.predict_fix",
            return_value=[
                {
                    "confidence": 40,
                    "cause": "Misleading retriever cause",
                    "fix": "Misleading retriever fix",
                    "error_type": "SyntaxError",
                    "retriever_backend": "embedding_retriever",
                }
            ],
        ), patch("core.decision_engine._brain_v1_decision", return_value=None):
            decision = decide_fix(
                {"raw": "Traceback\nSyntaxError: expected ':'", "type": "SyntaxError", "message": "expected ':'"},
                {"line": "def login(user)"},
            )

        self.assertEqual(decision.cause, "The function definition is missing a colon.")
        self.assertEqual(decision.fix, "Add a colon at the end of the function definition.")

    def test_non_python_autofix_remains_disabled(self):
        diagnostic = diagnose_non_python(
            "ReferenceError: missingValue is not defined\n"
            "    at Object.<anonymous> (app.js:1:1)\n",
            command="node app.js",
        )

        self.assertFalse(diagnostic["auto_fix_available"])
        self.assertEqual(diagnostic["safety_reason"], "Auto-fix is disabled for non-Python languages.")


if __name__ == "__main__":
    unittest.main()
