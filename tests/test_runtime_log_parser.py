from __future__ import annotations

import unittest

from core.parser import extract_runtime_error, parse_error


class RuntimeLogParserTests(unittest.TestCase):
    def test_python_traceback_extracted_from_noisy_logs(self):
        output = (
            "INFO: watching files\n"
            "Traceback (most recent call last):\n"
            "  File \"app.py\", line 2, in <module>\n"
            "    import missing_pkg\n"
            "ModuleNotFoundError: No module named 'missing_pkg'\n"
            "INFO: server stopped\n"
        )

        extracted = extract_runtime_error(output, command="python app.py")

        self.assertEqual(extracted["language"], "python")
        self.assertEqual(extracted["type"], "ModuleNotFoundError")
        self.assertEqual(extracted["missing_package"], "missing_pkg")
        self.assertEqual(extracted["kind"], "python_traceback")

    def test_django_runserver_error_extracts_framework(self):
        output = (
            "Watching for file changes with StatReloader\n"
            "Traceback (most recent call last):\n"
            "  File \"manage.py\", line 22, in <module>\n"
            "    main()\n"
            "django.core.exceptions.ImproperlyConfigured: SECRET_KEY is required\n"
        )

        extracted = extract_runtime_error(output, command="python manage.py runserver")

        self.assertEqual(extracted["framework"], "django")
        self.assertEqual(extracted["type"], "ImproperlyConfigured")

    def test_uvicorn_startup_error_extracts_framework(self):
        output = (
            "INFO:     Started reloader process\n"
            "Traceback (most recent call last):\n"
            "  File \"main.py\", line 2, in <module>\n"
            "    from missing_pkg import tool\n"
            "ModuleNotFoundError: No module named 'missing_pkg'\n"
        )

        extracted = extract_runtime_error(output, command="uvicorn main:app --reload")

        self.assertEqual(extracted["framework"], "fastapi")
        self.assertEqual(extracted["type"], "ModuleNotFoundError")

    def test_node_stack_trace_extracts_error(self):
        output = (
            "Server starting\n"
            "ReferenceError: missingValue is not defined\n"
            "    at Object.<anonymous> (C:\\repo\\server.js:4:1)\n"
            "    at Module._compile (node:internal/modules/cjs/loader:1358:14)\n"
        )

        extracted = extract_runtime_error(output, command="npm run dev")

        self.assertEqual(extracted["language"], "javascript/node")
        self.assertEqual(extracted["type"], "ReferenceError")
        self.assertEqual(extracted["kind"], "node_stack")

    def test_port_in_use_is_structured(self):
        extracted = extract_runtime_error(
            "Error: listen EADDRINUSE: address already in use :::3000\n",
            command="npm run dev",
        )

        self.assertEqual(extracted["type"], "PortInUse")
        self.assertEqual(extracted["kind"], "port_in_use")

    def test_npm_missing_package_json_is_structured(self):
        output = (
            "npm ERR! code ENOENT\n"
            "npm ERR! syscall open\n"
            "npm ERR! path C:\\repo\\package.json\n"
            "npm ERR! enoent Could not read package.json: Error: ENOENT: no such file or directory, open 'C:\\repo\\package.json'\n"
        )

        extracted = extract_runtime_error(output, command="npm run dev")

        self.assertEqual(extracted["type"], "NpmPackageJsonMissingError")
        self.assertEqual(extracted["kind"], "npm_package_json_missing")

    def test_uvicorn_command_not_found_is_structured(self):
        extracted = extract_runtime_error(
            "'uvicorn' is not recognized as an internal or external command,\n"
            "operable program or batch file.\n",
            command="uvicorn main:app --reload",
        )

        self.assertEqual(extracted["type"], "CommandNotFoundError")
        self.assertEqual(extracted["kind"], "command_not_found")

    def test_parse_error_keeps_environment_keyerror(self):
        parsed = parse_error(
            "Traceback (most recent call last):\n"
            "  File \"settings.py\", line 4, in <module>\n"
            "    DATABASE_URL = os.environ['DATABASE_URL']\n"
            "KeyError: 'DATABASE_URL'\n"
        )

        self.assertEqual(parsed["type"], "KeyError")
        self.assertEqual(parsed["message"], "'DATABASE_URL'")


if __name__ == "__main__":
    unittest.main()
