#!/usr/bin/env python3
"""config-drift - Detect configuration drift across environments.

Zero-dependency CLI that compares configuration files across environments
(like dev/, staging/, prod/), detects drift, and optionally applies safe
non-secret changes.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

__version__ = "0.1.1"

SUPPORTED_FORMATS = (".json", ".properties", ".toml", ".yaml", ".yml")

SECRET_PATTERN = re.compile(
    r"(password|passwd|pwd|secret|token|api[_-]?key|private[_-]?key|access[_-]?key|auth)",
    re.IGNORECASE,
)

SAFE_ENV_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")

# Try importing optional parsers (ok if absent)
try:
    import yaml as _yaml

    HAS_YAML = True
except ImportError:
    HAS_YAML = False

try:
    import tomllib as _tomllib

    HAS_TOML = True
except ImportError:
    try:
        import tomli as _tomllib

        HAS_TOML = True
    except ImportError:
        HAS_TOML = False


def load_json(path: Path) -> dict[str, Any]:
    """Load a JSON file."""
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_properties(path: Path) -> dict[str, Any]:
    """Load a Java .properties file."""
    result: dict[str, Any] = {}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(("#", "!")):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if key:
                    result[key] = _parse_properties_value(value)
            elif ":" in line:
                key, _, value = line.partition(":")
                key = key.strip()
                value = value.strip()
                if key:
                    result[key] = _parse_properties_value(value)
    return result


def _parse_properties_value(value: str) -> Any:
    """Attempt to parse a .properties value as a Python type.

    Handles Java .properties escape sequences: \\n, \\t, \\=, \\: \\\\
    """
    # Handle escape sequences
    if "\\" in value:
        value = (
            value.replace("\\n", "\n")
            .replace("\\t", "\t")
            .replace("\\=", "=")
            .replace("\\:", ":")
            .replace("\\\\", "\\")
        )
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def load_toml(path: Path) -> dict[str, Any]:
    """Load a TOML file, if a parser is available."""
    if not HAS_TOML:
        print(f"Warning: No TOML parser available, skipping {path}", file=sys.stderr)
        return {}
    with path.open("rb") as f:
        return _tomllib.load(f)


def load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file, if a parser is available."""
    if not HAS_YAML:
        print(f"Warning: No YAML parser available, skipping {path}", file=sys.stderr)
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = _yaml.safe_load(f)
        if data is None:
            return {}
        if not isinstance(data, dict):
            print(
                f"Warning: YAML root in {path} is not a mapping, skipping",
                file=sys.stderr,
            )
            return {}
        return data


LOADERS = {
    ".json": load_json,
    ".properties": load_properties,
    ".toml": load_toml,
    ".yaml": load_yaml,
    ".yml": load_yaml,
}


def load_config(path: Path) -> dict[str, Any]:
    """Load a config file, auto-detecting the format by extension."""
    ext = path.suffix.lower()
    loader = LOADERS.get(ext)
    if loader is None:
        print(f"Warning: Unsupported format {ext}, skipping {path}", file=sys.stderr)
        return {}
    return loader(path)


def flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten a nested structure to dot-notation keys."""
    items: dict[str, Any] = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            new_key = f"{prefix}.{key}" if prefix else key
            items.update(flatten(value, new_key))
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            new_key = f"{prefix}.{index}" if prefix else str(index)
            items.update(flatten(value, new_key))
    else:
        items[prefix] = obj
    return items


def is_secret_key(key: str, pattern: re.Pattern = SECRET_PATTERN) -> bool:
    """Check if a key looks like a secret."""
    return bool(pattern.search(key))


def validate_env_name(env: str) -> bool:
    """Validate environment name to prevent path traversal."""
    return bool(SAFE_ENV_PATTERN.match(env))


def find_config_files(root: Path, environments: list[str]) -> dict[str, list[Path]]:
    """Find config files in a directory tree."""
    result: dict[str, list[Path]] = {}

    for env in environments:
        env_dir = root / env
        if env_dir.is_dir():
            result[env] = sorted(
                p for p in env_dir.rglob("*") if p.suffix.lower() in SUPPORTED_FORMATS
            )

    if not result:
        for env in environments:
            # Use regex to match .env at end of stem
            # (e.g., app.dev.json -> stem "app.dev")
            # This avoids matching files like "deviant.json" for env "dev"
            env_regex = re.compile(rf"^[^.]*\.{re.escape(env)}$")
            files = sorted(
                p
                for p in root.glob("*")
                if p.suffix.lower() in SUPPORTED_FORMATS and env_regex.match(p.stem)
            )
            if files:
                result[env] = files

    return result


def normalize_for_comparison(value: Any) -> tuple[str, Any]:
    """Normalize a value for comparison, returning (type_name, comparable_value).

    Preserves int vs float distinction to detect type drift.
    Bools are handled before int check since bool is a subclass of int.
    """
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, int):
        return ("int", value)
    if isinstance(value, float):
        return ("float", value)
    if isinstance(value, str):
        return ("str", value)
    return (type(value).__name__, value)


def compare_environments(
    env_file_configs: dict[str, dict[str, dict[str, Any]]],
    secret_pattern: re.Pattern = SECRET_PATTERN,
) -> dict[str, list[dict[str, Any]]]:
    """Compare flattened configs across environments, per file.

    Args:
        env_file_configs: {env_name: {file_name: {flat_key: value}}}

    Returns:
        {file_name: [drift_entries]}
    """
    # Collect all file names and all keys per file
    all_files: set[str] = set()
    all_keys_by_file: dict[str, set[str]] = {}
    for env, file_configs in env_file_configs.items():
        for file_name, flat in file_configs.items():
            all_files.add(file_name)
            if file_name not in all_keys_by_file:
                all_keys_by_file[file_name] = set()
            all_keys_by_file[file_name].update(flat.keys())

    result: dict[str, list[dict[str, Any]]] = {}

    for file_name in sorted(all_files):
        all_keys = all_keys_by_file[file_name]
        drifts: list[dict[str, Any]] = []

        for key in sorted(all_keys):
            present: dict[str, Any] = {}
            missing: list[str] = []
            for env, file_configs in env_file_configs.items():
                flat = file_configs.get(file_name, {})
                if key in flat:
                    present[env] = flat[key]
                else:
                    missing.append(env)

            if not present:
                continue

            # Check for value drift using normalized comparison
            normalized_values: dict[str, tuple[str, Any]] = {}
            for env, v in present.items():
                normalized_values[env] = normalize_for_comparison(v)

            first_env = next(iter(normalized_values))
            first_type, first_normalized = normalized_values[first_env]
            has_value_drift = any(
                v != first_normalized
                for env, (_, v) in normalized_values.items()
                if env != first_env
            )

            # Check for type drift
            type_names: dict[str, str] = {
                env: tn for env, (tn, _) in normalized_values.items()
            }
            has_type_drift = len(set(type_names.values())) > 1

            if has_value_drift or has_type_drift or missing:
                formatted_values = {}
                for env, v in present.items():
                    if is_secret_key(key, secret_pattern):
                        formatted_values[env] = "***"
                    elif has_type_drift:
                        formatted_values[env] = f"{v} ({type_names[env]})"
                    else:
                        formatted_values[env] = str(v)

                if missing:
                    entry_type = "missing_key"
                elif has_type_drift:
                    entry_type = "type_drift"
                else:
                    entry_type = "value_drift"

                entry = {
                    "key": key,
                    "type": entry_type,
                    "secret": is_secret_key(key, secret_pattern),
                    "values": formatted_values,
                    "missing_in": sorted(missing),
                }
                if has_type_drift:
                    entry["type_names"] = type_names
                drifts.append(entry)

        if drifts:
            result[file_name] = drifts

    return result


def generate_terminal_report(
    configs_root: str,
    environments: list[str],
    file_drifts: dict[str, list[dict[str, Any]]],
    summary: dict[str, int],
) -> str:
    """Generate a terminal-friendly drift report."""
    lines = [
        "CONFIG DRIFT REPORT",
        f"Configs root: {configs_root}",
        f"Environments: {', '.join(environments)}",
        "",
    ]

    for file_name, drifts in file_drifts.items():
        lines.append(f"File: {file_name}")
        for drift in drifts:
            label = drift["type"].replace("_", " ").upper()
            lines.append(f"  [{label}] {drift['key']}")
            for env, value in drift["values"].items():
                lines.append(f"    {env + ':':12} {value}")
            if drift["missing_in"]:
                lines.append(f"    missing in: {', '.join(drift['missing_in'])}")
        lines.append("")

    lines.append("Summary:")
    lines.append(f"  Files compared: {summary['files_compared']}")
    lines.append(f"  Drifts found:   {summary['drifts_found']}")
    lines.append(f"  Missing keys:   {summary['missing_keys']}")

    return "\n".join(lines)


def generate_json_report(
    configs_root: str,
    environments: list[str],
    file_drifts: dict[str, list[dict[str, Any]]],
    summary: dict[str, int],
) -> str:
    """Generate a JSON drift report."""
    files_output = []
    for file_name, drifts in file_drifts.items():
        entries = []
        for drift in drifts:
            entry = {
                "key": drift["key"],
                "type": drift["type"],
                "secret": drift["secret"],
                "values": drift["values"],
                "missing_in": drift["missing_in"],
            }
            if drift.get("type_names"):
                entry["type_names"] = drift["type_names"]
            entries.append(entry)
        files_output.append({"file": file_name, "drifts": entries})

    report = {
        "configs_root": configs_root,
        "environments": environments,
        "files": files_output,
        "summary": summary,
    }
    return json.dumps(report, indent=2)


def generate_markdown_report(
    configs_root: str,
    environments: list[str],
    file_drifts: dict[str, list[dict[str, Any]]],
    summary: dict[str, int],
) -> str:
    """Generate a Markdown drift report."""
    lines = [
        "# Config Drift Report",
        "",
        f"**Configs root:** `{configs_root}`",
        f"**Environments:** {', '.join(f'`{e}`' for e in environments)}",
        "",
    ]

    for file_name, drifts in file_drifts.items():
        lines.append(f"## {file_name}")
        lines.append("")
        for drift in drifts:
            label = drift["type"].replace("_", " ").title()
            lines.append(f"### `{drift['key']}` ({label})")
            lines.append("")
            for env, value in drift["values"].items():
                lines.append(f"- **{env}:** `{value}`")
            if drift["missing_in"]:
                lines.append(f"- **missing in:** {', '.join(drift['missing_in'])}")
            lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Files compared: {summary['files_compared']}")
    lines.append(f"- Drifts found: {summary['drifts_found']}")
    lines.append(f"- Missing keys: {summary['missing_keys']}")

    return "\n".join(lines)


def diff_command(args: argparse.Namespace, secret_pattern: re.Pattern) -> int:
    """Run the diff command."""
    root = Path(args.configs_root)
    if not root.is_dir():
        print(f"Error: {root} is not a directory", file=sys.stderr)
        return 1

    environments = [e.strip() for e in args.environments.split(",")]

    # Validate environment names
    for env in environments:
        if not validate_env_name(env):
            print(
                f"Error: Invalid environment name '{env}'. "
                "Use only alphanumeric, underscore, or hyphen.",
                file=sys.stderr,
            )
            return 1

    found = find_config_files(root, environments)

    if not found:
        print("No config files found.", file=sys.stderr)
        return 1

    # Build per-file, per-environment config map
    env_file_configs: dict[str, dict[str, dict[str, Any]]] = {}
    file_names: set[str] = set()
    for env in environments:
        env_file_configs[env] = {}
        for f in found.get(env, []):
            file_names.add(f.name)
            loaded = load_config(f)
            if loaded:
                env_file_configs[env][f.name] = flatten(loaded)

    file_drifts = compare_environments(env_file_configs, secret_pattern)

    summary = {
        "files_compared": len(file_names),
        "drifts_found": sum(len(d) for d in file_drifts.values()),
        "missing_keys": sum(
            sum(1 for d in drifts if d["missing_in"]) for drifts in file_drifts.values()
        ),
    }

    if args.output_format == "terminal":
        report = generate_terminal_report(str(root), environments, file_drifts, summary)
    elif args.output_format == "json":
        report = generate_json_report(str(root), environments, file_drifts, summary)
    elif args.output_format == "markdown":
        report = generate_markdown_report(str(root), environments, file_drifts, summary)
    else:
        print(f"Error: Unknown format {args.output_format}", file=sys.stderr)
        return 1

    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        print(f"Report written to {args.output}")
    else:
        print(report)

    return 1 if (args.fail_on_drift and file_drifts) else 0


def apply_command(args: argparse.Namespace, secret_pattern: re.Pattern) -> int:
    """Run the apply command."""
    root = Path(args.configs_root)
    if not root.is_dir():
        print(f"Error: {root} is not a directory", file=sys.stderr)
        return 1

    # Validate environment names
    for env in [args.source, args.target]:
        if not validate_env_name(env):
            print(
                f"Error: Invalid environment name '{env}'. "
                "Use only alphanumeric, underscore, or hyphen.",
                file=sys.stderr,
            )
            return 1

    source = args.source
    target = args.target
    found = find_config_files(root, [source, target])

    if source not in found:
        print(f"Error: Source environment '{source}' not found.", file=sys.stderr)
        return 1
    if target not in found:
        print(f"Error: Target environment '{target}' not found.", file=sys.stderr)
        return 1

    source_files = {f.name: f for f in found.get(source, [])}
    target_files = {f.name: f for f in found.get(target, [])}

    # Actually write the changes to target files
    applied_count = 0
    for file_name, source_path in source_files.items():
        if file_name not in target_files:
            continue
        target_path = target_files[file_name]
        source_config = load_config(source_path)
        target_config = load_config(target_path)

        # Add missing keys
        source_flat = flatten(source_config)
        target_flat = flatten(target_config)
        for key, value in sorted(source_flat.items()):
            if key not in target_flat:
                if is_secret_key(key, secret_pattern) and not args.include_secrets:
                    continue
                # Set the value in target_config
                parts = key.split(".")
                current = target_config
                for part in parts[:-1]:
                    if part not in current:
                        current[part] = {}
                    current = current[part]
                current[parts[-1]] = value
                applied_count += 1

        if applied_count > 0:
            # Write the updated config
            ext = target_path.suffix.lower()
            if ext == ".json":
                with target_path.open("w", encoding="utf-8") as f:
                    json.dump(target_config, f, indent=2)
                    f.write("\n")
            elif ext == ".properties":
                with target_path.open("w", encoding="utf-8") as f:
                    for k, v in sorted(flatten(target_config).items()):
                        f.write(f"{k}={v}\n")
            elif ext in (".yaml", ".yml"):
                if HAS_YAML:
                    with target_path.open("w", encoding="utf-8") as f:
                        _yaml.safe_dump(target_config, f, default_flow_style=False)
                else:
                    print("Error: PyYAML not installed", file=sys.stderr)
            elif ext == ".toml":
                print("Error: Writing TOML is not supported", file=sys.stderr)

    if applied_count == 0:
        print("No missing keys to apply.")
        return 0

    print(f"Applied {applied_count} changes to {target} environment.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="config-drift - Detect configuration drift across environments"
    )
    parser.add_argument(
        "--version", action="version", version=f"config-drift {__version__}"
    )

    subparsers = parser.add_subparsers(dest="command", help="command to execute")

    diff_parser = subparsers.add_parser(
        "diff", help="detect drift between environments"
    )
    diff_parser.add_argument(
        "--configs-root",
        required=True,
        help="root directory containing config files",
    )
    diff_parser.add_argument(
        "--environments",
        required=True,
        help="comma-separated list of environments (e.g., dev,staging,prod)",
    )
    diff_parser.add_argument(
        "--output-format",
        choices=["terminal", "json", "markdown"],
        default="terminal",
        help="output format (default: terminal)",
    )
    diff_parser.add_argument(
        "--output",
        default=None,
        help="write report to file instead of stdout",
    )
    diff_parser.add_argument(
        "--secret-pattern",
        default=None,
        help="custom regex pattern for secret key detection",
    )
    diff_parser.add_argument(
        "--fail-on-drift",
        action="store_true",
        help="exit with code 1 if drift is detected",
    )

    apply_parser = subparsers.add_parser(
        "apply", help="apply missing keys from source to target environment"
    )
    apply_parser.add_argument(
        "--configs-root",
        required=True,
        help="root directory containing config files",
    )
    apply_parser.add_argument(
        "--source",
        required=True,
        help="source environment (copy from)",
    )
    apply_parser.add_argument(
        "--target",
        required=True,
        help="target environment (copy to)",
    )
    apply_parser.add_argument(
        "--yes",
        action="store_true",
        help="skip confirmation prompt",
    )
    apply_parser.add_argument(
        "--include-secrets",
        action="store_true",
        help="allow secret-looking keys to be copied (dangerous)",
    )
    apply_parser.add_argument(
        "--secret-pattern",
        default=None,
        help="custom regex pattern for secret key detection",
    )

    args = parser.parse_args()

    # Compile custom secret pattern if provided
    secret_pattern = SECRET_PATTERN
    if args.command and args.secret_pattern:
        secret_pattern = re.compile(args.secret_pattern, re.IGNORECASE)

    if args.command == "diff":
        sys.exit(diff_command(args, secret_pattern))
    elif args.command == "apply":
        sys.exit(apply_command(args, secret_pattern))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
