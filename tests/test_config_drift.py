#!/usr/bin/env python3
"""Tests for config-drift v0.1.1."""

import argparse
import json
import os
import re
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


class TestCustomSecretPattern(unittest.TestCase):
    """Test custom secret pattern via CLI flag."""

    def test_custom_pattern(self):
        """Custom pattern overrides default."""
        pattern = re.compile(r"custom_secret", re.IGNORECASE)
        self.assertTrue(pattern.search("my_custom_secret_key"))
        self.assertFalse(pattern.search("api_key"))

    def test_is_secret_key_with_custom_pattern(self):
        """is_secret_key respects custom pattern."""
        custom = re.compile(r"my_secret", re.IGNORECASE)
        self.assertTrue(config_drift.is_secret_key("my_secret_key", custom))
        self.assertFalse(config_drift.is_secret_key("api_key", custom))


class TestPropertiesEscapes(unittest.TestCase):
    """Test .properties escape sequence handling."""

    def test_newline_escape(self):
        fd, path = tempfile.mkstemp(suffix=".properties")
        try:
            os.write(fd, b"path=line1\\nline2\n")
            os.close(fd)
            result = config_drift.load_properties(Path(path))
            self.assertEqual(result["path"], "line1\nline2")
        finally:
            os.unlink(path)

    def test_tab_escape(self):
        fd, path = tempfile.mkstemp(suffix=".properties")
        try:
            os.write(fd, b"path=col1\\tcol2\n")
            os.close(fd)
            result = config_drift.load_properties(Path(path))
            self.assertEqual(result["path"], "col1\tcol2")
        finally:
            os.unlink(path)

    def test_escaped_equals(self):
        fd, path = tempfile.mkstemp(suffix=".properties")
        try:
            os.write(fd, b"equation=1\\=2\n")
            os.close(fd)
            result = config_drift.load_properties(Path(path))
            self.assertEqual(result["equation"], "1=2")
        finally:
            os.unlink(path)

    def test_escaped_backslash(self):
        fd, path = tempfile.mkstemp(suffix=".properties")
        try:
            os.write(fd, b"path=C\\\\Users\\\\foo\n")
            os.close(fd)
            result = config_drift.load_properties(Path(path))
            self.assertEqual(result["path"], "C\\Users\\foo")
        finally:
            os.unlink(path)


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

    def test_flat_structure_no_false_positive(self):
        """Files like 'deviant.json' should NOT match env 'dev'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "deviant.json").write_text("{}")
            (root / "my.dev.json").write_text("{}")

            result = config_drift.find_config_files(root, ["dev"])
            self.assertIn("dev", result)
            self.assertEqual(len(result["dev"]), 1)
            self.assertEqual(result["dev"][0].name, "my.dev.json")


class TestNormalizeForComparison(unittest.TestCase):
    """Test normalize_for_comparison preserves int vs float."""

    def test_int_vs_float(self):
        """int and float are distinct types."""
        self.assertEqual(config_drift.normalize_for_comparison(42), ("int", 42))
        self.assertEqual(config_drift.normalize_for_comparison(42.0), ("float", 42.0))

    def test_bool_not_int(self):
        """bool is not conflated with int."""
        self.assertEqual(config_drift.normalize_for_comparison(True), ("bool", True))
        self.assertEqual(config_drift.normalize_for_comparison(False), ("bool", False))

    def test_string(self):
        self.assertEqual(
            config_drift.normalize_for_comparison("hello"), ("str", "hello")
        )


class TestFileLevelDriftAttribution(unittest.TestCase):
    """Test drift is attributed to correct file."""

    def test_drift_per_file(self):
        """Drift appears only in the file that contains it."""
        env_file_configs = {
            "dev": {
                "app.json": {"app.name": "myapp", "app.debug": True},
                "db.json": {"db.host": "localhost"},
            },
            "prod": {
                "app.json": {"app.name": "myapp", "app.debug": False},
                "db.json": {"db.host": "prod-host"},
            },
        }
        result = config_drift.compare_environments(env_file_configs)
        # app.json should have drift on app.debug
        self.assertIn("app.json", result)
        app_drifts = [d["key"] for d in result["app.json"]]
        self.assertIn("app.debug", app_drifts)
        # db.json should have drift on db.host
        self.assertIn("db.json", result)
        db_drifts = [d["key"] for d in result["db.json"]]
        self.assertIn("db.host", db_drifts)
        # app.json should NOT have db.host drift
        self.assertNotIn("db.host", app_drifts)

    def test_no_drift(self):
        env_file_configs = {
            "dev": {"app.json": {"a": 1}},
            "prod": {"app.json": {"a": 1}},
        }
        result = config_drift.compare_environments(env_file_configs)
        self.assertEqual(result, {})


class TestIntFloatTypeDrift(unittest.TestCase):
    """Test int vs float is flagged as type drift."""

    def test_int_to_float_drift(self):
        """port: 3000 (int) vs port: 3000.0 (float) is type drift."""
        env_file_configs = {
            "dev": {"app.json": {"port": 3000}},
            "prod": {"app.json": {"port": 3000.0}},
        }
        result = config_drift.compare_environments(env_file_configs)
        self.assertIn("app.json", result)
        drift = result["app.json"][0]
        self.assertEqual(drift["type"], "type_drift")

    def test_same_int_no_drift(self):
        env_file_configs = {
            "dev": {"app.json": {"port": 3000}},
            "prod": {"app.json": {"port": 3000}},
        }
        result = config_drift.compare_environments(env_file_configs)
        self.assertEqual(result, {})


class TestBooleanNormalization(unittest.TestCase):
    """Test boolean normalization."""

    def test_bool_vs_int(self):
        """bool True is different from int 1."""
        env_file_configs = {
            "dev": {"app.json": {"flag": True}},
            "prod": {"app.json": {"flag": 1}},
        }
        result = config_drift.compare_environments(env_file_configs)
        # True (bool) vs 1 (int) is type drift
        self.assertIn("app.json", result)

    def test_bool_vs_string(self):
        """bool True is different from string 'true'."""
        env_file_configs = {
            "dev": {"app.json": {"flag": True}},
            "prod": {"app.json": {"flag": "true"}},
        }
        result = config_drift.compare_environments(env_file_configs)
        self.assertIn("app.json", result)


class TestEnvironmentValidation(unittest.TestCase):
    """Test environment name validation."""

    def test_valid_names(self):
        self.assertTrue(config_drift.validate_env_name("dev"))
        self.assertTrue(config_drift.validate_env_name("staging"))
        self.assertTrue(config_drift.validate_env_name("prod"))
        self.assertTrue(config_drift.validate_env_name("my-env"))
        self.assertTrue(config_drift.validate_env_name("env_1"))

    def test_invalid_names(self):
        self.assertFalse(config_drift.validate_env_name("../etc"))
        self.assertFalse(config_drift.validate_env_name("env/path"))
        self.assertFalse(config_drift.validate_env_name("env.."))
        self.assertFalse(config_drift.validate_env_name(""))


class TestApplyCommand(unittest.TestCase):
    """Test apply command actually writes changes."""

    def test_apply_writes_missing_keys(self):
        """Apply command adds missing keys to target."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "dev").mkdir()
            (root / "prod").mkdir()

            dev_config = {"app": {"name": "myapp", "debug": True, "cache": True}}
            prod_config = {"app": {"name": "myapp", "debug": False}}

            (root / "dev" / "app.json").write_text(json.dumps(dev_config))
            (root / "prod" / "app.json").write_text(json.dumps(prod_config))

            args = argparse.Namespace(
                configs_root=str(root),
                source="dev",
                target="prod",
                yes=True,
                include_secrets=False,
                secret_pattern=None,
            )

            pattern = re.compile(
                r"(password|passwd|pwd|secret|token|api[_-]?key|private[_-]?key|access[_-]?key|auth)",
                re.IGNORECASE,
            )
            exit_code = config_drift.apply_command(args, pattern)
            self.assertEqual(exit_code, 0)

            result = json.loads((root / "prod" / "app.json").read_text())
            self.assertIn("cache", result["app"])
            self.assertEqual(result["app"]["cache"], True)

    def test_apply_skips_secrets(self):
        """Apply command skips secret keys by default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "dev").mkdir()
            (root / "prod").mkdir()

            dev_config = {"db": {"host": "localhost", "password": "secret123"}}
            prod_config = {"db": {"host": "prod-host"}}

            (root / "dev" / "app.json").write_text(json.dumps(dev_config))
            (root / "prod" / "app.json").write_text(json.dumps(prod_config))

            args = argparse.Namespace(
                configs_root=str(root),
                source="dev",
                target="prod",
                yes=True,
                include_secrets=False,
                secret_pattern=None,
            )

            pattern = re.compile(
                r"(password|passwd|pwd|secret|token|api[_-]?key|private[_-]?key|access[_-]?key|auth)",
                re.IGNORECASE,
            )
            exit_code = config_drift.apply_command(args, pattern)
            self.assertEqual(exit_code, 0)

            result = json.loads((root / "prod" / "app.json").read_text())
            self.assertNotIn("password", result["db"])

    def test_apply_missing_source(self):
        """Apply errors when source env not found."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "dev").mkdir()

            args = argparse.Namespace(
                configs_root=str(root),
                source="nonexistent",
                target="dev",
                yes=True,
                include_secrets=False,
                secret_pattern=None,
            )

            pattern = re.compile(r"secret", re.IGNORECASE)
            exit_code = config_drift.apply_command(args, pattern)
            self.assertEqual(exit_code, 1)

    def test_apply_missing_target(self):
        """Apply errors when target env not found."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "dev").mkdir()

            args = argparse.Namespace(
                configs_root=str(root),
                source="dev",
                target="nonexistent",
                yes=True,
                include_secrets=False,
                secret_pattern=None,
            )

            pattern = re.compile(r"secret", re.IGNORECASE)
            exit_code = config_drift.apply_command(args, pattern)
            self.assertEqual(exit_code, 1)


class TestDiffCommandValidation(unittest.TestCase):
    """Test diff command validation."""

    def test_invalid_env_name(self):
        """Diff rejects invalid environment names."""
        with tempfile.TemporaryDirectory() as tmpdir:
            args = argparse.Namespace(
                configs_root=tmpdir,
                environments="../etc,prod",
                output_format="terminal",
                output=None,
                secret_pattern=None,
                fail_on_drift=False,
            )

            pattern = re.compile(r"secret", re.IGNORECASE)
            exit_code = config_drift.diff_command(args, pattern)
            self.assertEqual(exit_code, 1)


class TestCLISecretPatternIntegration(unittest.TestCase):
    """Test that --secret-pattern flows through CLI to comparison logic."""

    def test_secret_pattern_in_diff(self):
        """Custom secret pattern masks custom keys in diff."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "dev").mkdir()
            (root / "prod").mkdir()

            dev = {"app": {"name": "myapp"}, "my_custom_secret": "dev_value"}
            prod = {"app": {"name": "myapp"}, "my_custom_secret": "prod_value"}

            (root / "dev" / "app.json").write_text(json.dumps(dev))
            (root / "prod" / "app.json").write_text(json.dumps(prod))

            args = argparse.Namespace(
                configs_root=str(root),
                environments="dev,prod",
                output_format="terminal",
                output=None,
                secret_pattern=r"my_custom_secret",
                fail_on_drift=True,
            )

            pattern = re.compile(r"my_custom_secret", re.IGNORECASE)
            exit_code = config_drift.diff_command(args, pattern)
            self.assertEqual(exit_code, 1)  # drift detected


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

            env_file_configs = {}
            for env in ["dev", "prod"]:
                env_file_configs[env] = {}
                for f in found[env]:
                    loaded = config_drift.load_config(f)
                    if loaded:
                        env_file_configs[env][f.name] = config_drift.flatten(loaded)

            file_drifts = config_drift.compare_environments(env_file_configs)
            self.assertIn("app.json", file_drifts)

            debug_drifts = [
                d for d in file_drifts["app.json"] if d["key"] == "app.debug"
            ]
            self.assertEqual(len(debug_drifts), 1)
            self.assertEqual(debug_drifts[0]["type"], "value_drift")


if __name__ == "__main__":
    unittest.main()
