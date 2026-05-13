from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from typer.testing import CliRunner

from cli.main import app
from core.event_classifier import (
    APP_BUG,
    AUTH_ANOMALY,
    EXPECTED_USER_ERROR,
    INFRASTRUCTURE_ERROR,
    REPEATED_FAILURE,
    classify_log_text,
)
from core.production_signals import RuntimeSignal


class EventClassifierTests(unittest.TestCase):
    def test_single_wrong_password_401_is_expected_user_error(self):
        result = classify_log_text("POST /login 401 invalid password for user alice")

        self.assertEqual(result.category, EXPECTED_USER_ERROR)
        self.assertEqual(result.severity, "info")
        self.assertFalse(result.brain_escalation_needed)
        self.assertTrue(result.expected_behavior)
        self.assertFalse(result.likely_bug)

    def test_many_401s_become_auth_anomaly(self):
        log = "\n".join(f"POST /login 401 invalid password attempt={i}" for i in range(6))

        result = classify_log_text("deploy completed\n" + log)

        self.assertEqual(result.category, AUTH_ANOMALY)
        self.assertIn("repeated_401_403_spike", result.anomalies)
        self.assertFalse(result.brain_escalation_needed)
        self.assertTrue(result.likely_bug)

    def test_500_error_becomes_app_bug(self):
        result = classify_log_text("GET /api/orders 500 Internal Server Error")

        self.assertEqual(result.category, APP_BUG)
        self.assertEqual(result.severity, "error")
        self.assertTrue(result.brain_escalation_needed)

    def test_db_timeout_becomes_infrastructure_error(self):
        result = classify_log_text("database connection timed out while reading orders")

        self.assertEqual(result.category, INFRASTRUCTURE_ERROR)
        self.assertTrue(result.brain_escalation_needed)

    def test_repeated_same_traceback_becomes_repeated_failure(self):
        traceback = (
            "Traceback (most recent call last):\n"
            "  File \"app.py\", line 1, in <module>\n"
            "ValueError: broken\n"
        )

        result = classify_log_text(traceback * 3)

        self.assertEqual(result.category, REPEATED_FAILURE)
        self.assertIn("same_traceback_repeated", result.anomalies)


class IntegrationStubTests(unittest.TestCase):
    def test_sentry_posthog_clarity_stubs_need_no_network_or_api_keys(self):
        from integrations import clarity, posthog, sentry

        for module in (sentry, posthog, clarity):
            parsed = module.parse_event({"message": "hello"})
            normalized = module.normalize_event({"message": "hello"})

            self.assertFalse(parsed["enabled"])
            self.assertEqual(parsed["signals"], [])
            self.assertIsInstance(normalized, RuntimeSignal)
            self.assertFalse(normalized.metadata["enabled"])


class ClassifyLogCommandTests(unittest.TestCase):
    def test_classify_log_command_works(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "app.log"
            log_path.write_text("GET /checkout 500 Internal Server Error\n", encoding="utf-8")

            result = runner.invoke(app, ["classify-log", str(log_path)], catch_exceptions=False)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("app_bug", result.output)
        self.assertIn("severity", result.output)
        self.assertIn("brain escalation needed", result.output)


if __name__ == "__main__":
    unittest.main()
