from __future__ import annotations

import importlib.metadata
import shutil
import tomllib
import unittest
from pathlib import Path

import typer


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    def test_entrypoint_import_works(self):
        from cli.main import app

        self.assertIsInstance(app, typer.Typer)

    def test_ghostfix_command_resolves_or_is_declared(self):
        command = shutil.which("ghostfix")
        script = self.pyproject["project"]["scripts"]["ghostfix"]

        self.assertEqual(script, "cli.main:app")
        self.assertTrue(command or script)

    def test_package_metadata_loads(self):
        project = self.pyproject["project"]

        self.assertEqual(project["name"], "ghostfix-ai")
        self.assertEqual(project["version"], "0.3.0")
        self.assertEqual(project["readme"], "README.md")
        self.assertEqual(project["requires-python"], ">=3.10")
        self.assertEqual(project["license"]["text"], "MIT")
        self.assertIn("description", project)
        try:
            metadata = importlib.metadata.metadata("ghostfix-ai")
        except importlib.metadata.PackageNotFoundError:
            metadata = None
        if metadata is not None:
            self.assertEqual(metadata["Name"], "ghostfix-ai")

    def test_editable_install_compatibility_config(self):
        build_system = self.pyproject["build-system"]
        packages = self.pyproject["tool"]["setuptools"]["packages"]["find"]

        self.assertEqual(build_system["build-backend"], "setuptools.build_meta")
        self.assertIn("setuptools>=61", build_system["requires"])
        self.assertIn("cli*", packages["include"])
        self.assertIn("core*", packages["include"])
        self.assertIn("tests*", packages["exclude"])
        self.assertIn("demos*", packages["exclude"])

    def test_optional_brain_dependencies_remain_optional(self):
        dependencies = "\n".join(self.pyproject["project"]["dependencies"])
        optional = self.pyproject["project"]["optional-dependencies"]

        self.assertNotIn("torch", dependencies)
        self.assertNotIn("transformers", dependencies)
        self.assertNotIn("scikit-learn", dependencies)
        self.assertNotIn("numpy", dependencies)
        self.assertIn("brain-v4", optional)
        self.assertIn("retriever", optional)
        self.assertTrue(any(item.startswith("torch") for item in optional["brain-v4"]))

    def test_distribution_excludes_generated_and_heavy_files(self):
        excluded = self.pyproject["tool"]["setuptools"]["exclude-package-data"]["*"]

        for pattern in [
            ".ghostfix/*",
            ".ml/*",
            "reports/*",
            "*.pyc",
            "*.bin",
            "*.ckpt",
            "*.pt",
            "*.pth",
            "*.safetensors",
            "*.pkl",
            "models/base_model/*",
            "models/*",
        ]:
            self.assertIn(pattern, excluded)

    def test_manifest_prunes_tests_docs_demos_and_local_state(self):
        manifest = Path("MANIFEST.in").read_text(encoding="utf-8")

        for line in [
            "prune tests",
            "prune demos",
            "prune docs",
            "prune .ghostfix",
            "prune .ml",
            "prune ml/reports",
            "global-exclude *.safetensors",
            "global-exclude *.pkl",
            "prune ml/models",
            "prune ml/processed",
        ]:
            self.assertIn(line, manifest)


if __name__ == "__main__":
    unittest.main()
