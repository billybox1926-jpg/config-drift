#!/usr/bin/env python3
"""Tests for config-drift v0.1.0."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

import config_drift


class TestLoadJson(unittest.TestCase):
    def test_load_valid_json(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump({"key": "value", "number": 42}, f)
            result = config_drift.load_json(Path(path))
            self.assertEqual(result, {"key": "value", "number": 42})
        finally:
            os.unlink(path)

    def test_load_nested_json(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump({"app": {"name": "test", "port": 3000}}, f)
            result = config_drift.load_json(Path(path))
            self.assertEqual(result["app"]["name"], "test")
        finally:
            os.unlink(path)


class TestLoadProperties(unittest.TestCase):
    def test_load_basic_properties(self):
        fd, path = tempfile.mkstemp(suffix=".properties")
        try:
            os.write(fd, b"host=localhost\nport=5432\nname=myapp\n")
            os.close(fd)
            result = config_drift.load_properties(Path(path))
            self.assertEqual(result["host"], "localhost")
            self.assertEqual(result["port"], 5432)
            self.assertEqual(result["name"], "myapp")
        finally:
            os.unlink(path)

    def test_load_properties_with_comments(self):
        fd, path = tempfile.mkstemp(suffix=".properties")
        try:
            os.write(
                fd,
                b"# This is a comment\nhost=localhost\n! Another comment\nport=5432\n",
            )
            os.close(fd)
            result = config_drift.load_properties(Path(path))
            self.assertEqual(result["host"], "localhost")
            self.assertEqual(result["port"], 5432)
            self.assertNotIn("# This is a comment", result)
        finally:
            os.unlink(path)

    def test_load_properties_with_colon_separator(self):
        fd, path = tempfile.mkstemp(suffix=".properties")
        try:
            os.write(fd, b"host: localhost\nport: 5432\n")
            os.close(fd)
            result = config_drift.load_properties(Path(path))
            self.assertEqual(result["host"], "localhost")
            self.assertEqual(result["port"], 5432)
        finally:
            os.unlink(path)

    def test_load_properties_boolean(self):
        fd, path = tempfile.mkstemp(suffix=".properties")
        try:
            os.write(fd, b"debug=true\nverbose=false\n")
            os.close(fd)
            result = config_drift.load_properties(Path(path))
            self.assertEqual(result["debug"], True)
            self.assertEqual(result["verbose"], False)
        finally:
            os.unlink(path)

    def test_load_properties_empty_lines(self):
        fd, path = tempfile.mkstemp(suffix=".properties")
        try:
            os.write(fd, b"\n\nhost=localhost\n\nport=5432\n\n")
            os.close(fd)
            result = config_drift.load_properties(Path(path))
            self.assertEqual(len(result), 2)
        finally:
            os.unlink(path)


class TestFlatten(unittest.TestCase):
    def test_flat_dict(self):
        result = config_drift.flatten({"a": 1, "b": 2})
        self.assertEqual(result, {"a": 1, "b": 2})

    def test_nested_dict(self):
        result = config_drift.flatten({"app": {"name": "test", "port": 3000}})
        self.assertEqual(result, {"app.name": "test", "app.port": 3000})

    def test_deeply_nested(self):
        result = config_drift.flatten({"a": {"b": {"c": 1}}})
        self.assertEqual(result, {"a.b.c": 1})

    def test_with_list(self):
        result = config_drift.flatten({"items": ["a", "b", "c"]})
        self.assertEqual(result, {"items.0": "a", "items.1": "b", "items.2": "c"})

    def test_empty_dict(self):
        result = config_drift.flatten({})
        self.assertEqual(result, {})

    def test_mixed_nested(self):
        result = config_drift.flatten({"app": {"ports": [3000, 3001]}})
        self.assertEqual(result, {"app.ports.0": 3000, "app.ports.1": 3001})


class TestSecretKeyDetection(unittest.TestCase):
    def test_password_keys(self):
        self.assertTrue(config_drift.is_secret_key("database.password"))
        self.assertTrue(config_drift.is_secret_key("user_password"))
        self.assertTrue(config_drift.is_secret_key("passwd"))

    def test_token_keys(self):
        self.assertTrue(config_drift.is_secret_key("api.token"))
        self.assertTrue(config_drift.is_secret_key("auth_token"))

    def test_api_key(self):
        self.assertTrue(config_drift.is_secret_key("api_key"))
        self.assertTrue(config_drift.is_secret_key("api-key"))
        self.assertTrue(config_drift.is_secret_key("apiKey"))

    def test_non_secret_keys(self):
        self.assertFalse(config_drift.is_secret_key("database.host"))
        self.assertFalse(config_drift.is_secret_key("app.name"))
        self.assertFalse(config_drift.is_secret_key("port"))

    def test_case_insensitive(self):
        self.assertTrue(config_drift.is_secret_key("PASSWORD"))
        self.assertTrue(config_drift.is_secret_key("Api_Key"))


class TestCompareEnvironments(unittest.TestCase):
    def test_no_drift(self):
        configs = {"dev": {"a": 1, "b": 2}, "staging": {"a": 1, "b": 2}}
        drifts = config_drift.compare_environments(configs)
        self.assertEqual(drifts, [])

    def test_value_drift(self):
        configs = {
            "dev": {"host": "localhost"},
            "staging": {"host": "staging.internal"},
        }
        drifts = config_drift.compare_environments(configs)
        self.assertEqual(len(drifts), 1)
        self.assertEqual(drifts[0]["type"], "value_drift")
        self.assertEqual(drifts[0]["key"], "host")

    def test_missing_key(self):
        configs = {"dev": {"a": 1, "b": 2}, "staging": {"a": 1}}
        drifts = config_drift.compare_environments(configs)
        self.assertEqual(len(drifts), 1)
        self.assertEqual(drifts[0]["type"], "missing_key")
        self.assertEqual(drifts[0]["missing_in"], ["staging"])

    def test_type_drift(self):
        configs = {"dev": {"port": 3000}, "staging": {"port": "3000"}}
        drifts = config_drift.compare_environments(configs)
        self.assertEqual(len(drifts), 1)
        self.assertEqual(drifts[0]["type"], "type_drift")

    def test_three_way_comparison(self):
        configs = {
            "dev": {"a": 1, "b": 2, "c": 3},
            "staging": {"a": 1, "b": 3},
            "prod": {"a": 2, "b": 2},
        }
        drifts = config_drift.compare_environments(configs)
        self.assertGreater(len(drifts), 0)


class TestFindConfigFiles(unittest.TestCase):
    def test_directory_structure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "dev").mkdir()
            (root / "staging").mkdir()
            (root / "prod").mkdir()
            (root / "dev" / "app.json").write_text("{}")
            (root / "staging" / "app.json").write_text("{}")
            (root / "prod" / "app.json").write_text("{}")

            result = config_drift.find_config_files(root, ["dev", "staging", "prod"])
            self.assertIn("dev", result)
            self.assertIn("staging", result)
            self.assertIn("prod", result)
            self.assertEqual(len(result["dev"]), 1)

    def test_flat_structure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "app.dev.json").write_text("{}")
            (root / "app.staging.json").write_text("{}")
            (root / "app.prod.json").write_text("{}")

            result = config_drift.find_config_files(root, ["dev", "staging", "prod"])
            self.assertIn("dev", result)
            self.assertIn("staging", result)
            self.assertIn("prod", result)


class TestReportGeneration(unittest.TestCase):
    def test_terminal_report(self):
        configs_root = "./configs"
        environments = ["dev", "staging", "prod"]
        file_groups = {
            "app.json": {
                "__all__": [
                    {
                        "key": "host",
                        "type": "value_drift",
                        "secret": False,
                        "values": {"dev": "localhost", "staging": "staging.internal"},
                        "missing_in": [],
                    }
                ]
            }
        }
        summary = {"files_compared": 1, "drifts_found": 1, "missing_keys": 0}

        report = config_drift.generate_terminal_report(
            configs_root, environments, file_groups, summary
        )
        self.assertIn("CONFIG DRIFT REPORT", report)
        self.assertIn("host", report)

    def test_json_report(self):
        configs_root = "./configs"
        environments = ["dev", "staging"]
        file_groups = {
            "app.json": {
                "__all__": [
                    {
                        "key": "host",
                        "type": "value_drift",
                        "secret": False,
                        "values": {"dev": "localhost", "staging": "staging.internal"},
                        "missing_in": [],
                    }
                ]
            }
        }
        summary = {"files_compared": 1, "drifts_found": 1, "missing_keys": 0}

        report = config_drift.generate_json_report(
            configs_root, environments, file_groups, summary
        )
        parsed = json.loads(report)
        self.assertEqual(parsed["summary"]["drifts_found"], 1)

    def test_markdown_report(self):
        configs_root = "./configs"
        environments = ["dev", "staging"]
        file_groups = {
            "app.json": {
                "__all__": [
                    {
                        "key": "host",
                        "type": "value_drift",
                        "secret": False,
                        "values": {"dev": "localhost", "staging": "staging.internal"},
                        "missing_in": [],
                    }
                ]
            }
        }
        summary = {"files_compared": 1, "drifts_found": 1, "missing_keys": 0}

        report = config_drift.generate_markdown_report(
            configs_root, environments, file_groups, summary
        )
        self.assertIn("# Config Drift Report", report)
        self.assertIn("host", report)


class TestEndToEnd(unittest.TestCase):
    def test_full_diff_workflow(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "dev").mkdir()
            (root / "prod").mkdir()

            dev_config = {"app": {"name": "myapp", "debug": True}, "port": 3000}
            prod_config = {"app": {"name": "myapp", "debug": False}, "port": 8080}

            (root / "dev" / "app.json").write_text(json.dumps(dev_config))
            (root / "prod" / "app.json").write_text(json.dumps(prod_config))

            found = config_drift.find_config_files(root, ["dev", "prod"])
            self.assertIn("dev", found)
            self.assertIn("prod", found)

            env_configs = {}
            for env in ["dev", "prod"]:
                combined = {}
                for f in found[env]:
                    combined.update(config_drift.flatten(config_drift.load_config(f)))
                env_configs[env] = combined

            drifts = config_drift.compare_environments(env_configs)
            self.assertGreater(len(drifts), 0)

            debug_drifts = [d for d in drifts if d["key"] == "app.debug"]
            self.assertEqual(len(debug_drifts), 1)
            self.assertEqual(debug_drifts[0]["type"], "value_drift")


if __name__ == "__main__":
    unittest.main()
