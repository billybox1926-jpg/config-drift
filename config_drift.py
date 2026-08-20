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

__version__ = "0.1.0"

SUPPORTED_FORMATS = (".json", ".properties", ".toml", ".yaml", ".yml")

SECRET_PATTERN = re.compile(
    r"(password|passwd|pwd|secret|token|api[_-]?key|private[_-]?key|access[_-]?key|auth)",
    re.IGNORECASE,
)

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
            files = sorted(
                p
                for p in root.glob("*")
                if p.suffix.lower() in SUPPORTED_FORMATS and f".{env}" in p.stem
            )
            if files:
                result[env] = files

    return result


def normalize_for_comparison(value: Any) -> Any:
    """Normalize a value for comparison (handle int vs float)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return float(value)
    return value


def compare_environments(
    configs: dict[str, dict[str, Any]],
    secret_pattern: re.Pattern = SECRET_PATTERN,
) -> list[dict[str, Any]]:
    """Compare flattened configs across environments."""
    all_keys: set[str] = set()
    for flat in configs.values():
        all_keys.update(flat.keys())

    drifts: list[dict[str, Any]] = []
    for key in sorted(all_keys):
        present: dict[str, Any] = {}
        missing: list[str] = []
        for env, flat in configs.items():
            if key in flat:
                present[env] = flat[key]
            else:
                missing.append(env)

        if not present:
            continue

        normalized_values: dict[str, Any] = {}
        for env, v in present.items():
            normalized_values[env] = normalize_for_comparison(v)

        first_env = next(iter(normalized_values))
        first_normalized = normalized_values[first_env]
        has_value_drift = any(
            v != first_normalized
            for env, v in normalized_values.items()
            if env != first_env
        )

        type_names: dict[str, str] = {
            env: type(v).__name__ for env, v in present.items()
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

    return drifts


def generate_terminal_report(
    configs_root: str,
    environments: list[str],
    file_groups: dict[str, dict[str, list[dict[str, Any]]]],
    summary: dict[str, int],
) -> str:
    """Generate a terminal-friendly drift report."""
    lines = [
        "CONFIG DRIFT REPORT",
        f"Configs root: {configs_root}",
        f"Environments: {', '.join(environments)}",
        "",
    ]

    for file_key, env_drifts in file_groups.items():
        lines.append(f"File: {file_key}")
        for drifts in env_drifts.values():
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
    file_groups: dict[str, dict[str, list[dict[str, Any]]]],
    summary: dict[str, int],
) -> str:
    """Generate a JSON drift report."""
    files_output = []
    for file_key, env_drifts in file_groups.items():
        drifts = []
        for drift in env_drifts.get("__all__", []):
            entry = {
                "key": drift["key"],
                "type": drift["type"],
                "secret": drift["secret"],
                "values": drift["values"],
                "missing_in": drift["missing_in"],
            }
            if drift.get("type_names"):
                entry["type_names"] = drift["type_names"]
            drifts.append(entry)
        files_output.append({"file": file_key, "drifts": drifts})

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
    file_groups: dict[str, dict[str, list[dict[str, Any]]]],
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

    for file_key, env_drifts in file_groups.items():
        lines.append(f"## {file_key}")
        lines.append("")
        for drift in env_drifts.get("__all__", []):
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


def _unflatten(flat: dict[str, Any]) -> dict[str, Any]:
    """Convert dot-notation keys back to nested dict."""
    result: dict[str, Any] = {}
    for key, value in flat.items():
        parts = key.split(".")
        current = result
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value
    return result


def _write_json(path: Path, data: dict[str, Any]) -> None:
    """Write data as JSON."""
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def _write_properties(path: Path, data: dict[str, Any]) -> None:
    """Write data as Java .properties."""
    with path.open("w", encoding="utf-8") as f:
        for key, value in sorted(data.items()):
            # Escape special characters
            val_str = str(value)
            val_str = (
                val_str.replace("\\", "\\\\")
                .replace("\n", "\\n")
                .replace("\t", "\\t")
                .replace("=", "\\=")
                .replace(":", "\\:")
            )
            f.write(f"{key}={val_str}\n")


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    """Write data as YAML."""
    if not HAS_YAML:
        print("Error: PyYAML not installed, cannot write YAML", file=sys.stderr)
        return
    with path.open("w", encoding="utf-8") as f:
        _yaml.safe_dump(data, f, default_flow_style=False)


def _write_toml(path: Path, data: dict[str, Any]) -> None:
    """Write data as TOML."""
    print("Error: Writing TOML is not supported (no safe serializer)", file=sys.stderr)


WRITERS = {
    ".json": _write_json,
    ".properties": _write_properties,
    ".yaml": _write_yaml,
    ".yml": _write_yaml,
    ".toml": _write_toml,
}


def diff_command(args: argparse.Namespace, secret_pattern: re.Pattern) -> int:
    """Run the diff command."""
    root = Path(args.configs_root)
    if not root.is_dir():
        print(f"Error: {root} is not a directory", file=sys.stderr)
        return 1

    environments = [e.strip() for e in args.environments.split(",")]
    found = find_config_files(root, environments)

    if not found:
        print("No config files found.", file=sys.stderr)
        return 1

    env_configs: dict[str, dict[str, Any]] = {}
    file_names: set[str] = set()

    for env in environments:
        files = found.get(env, [])
        combined: dict[str, Any] = {}
        for f in files:
            file_names.add(f.name)
            loaded = load_config(f)
            if loaded:
                combined.update(flatten(loaded))
        env_configs[env] = combined

    drifts = compare_environments(env_configs, secret_pattern)
    summary = {
        "files_compared": len(file_names),
        "drifts_found": len(drifts),
        "missing_keys": sum(1 for d in drifts if d["missing_in"]),
    }

    file_groups = {}
    for file_name in sorted(file_names):
        file_groups[file_name] = {"__all__": drifts}

    if args.output_format == "terminal":
        report = generate_terminal_report(str(root), environments, file_groups, summary)
    elif args.output_format == "json":
        report = generate_json_report(str(root), environments, file_groups, summary)
    elif args.output_format == "markdown":
        report = generate_markdown_report(str(root), environments, file_groups, summary)
    else:
        print(f"Error: Unknown format {args.output_format}", file=sys.stderr)
        return 1

    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        print(f"Report written to {args.output}")
    else:
        print(report)

    return 1 if (args.fail_on_drift and drifts) else 0


def apply_command(args: argparse.Namespace, secret_pattern: re.Pattern) -> int:
    """Run the apply command."""
    root = Path(args.configs_root)
    if not root.is_dir():
        print(f"Error: {root} is not a directory", file=sys.stderr)
        return 1

    source = args.source
    target = args.target
    found = find_config_files(root, [source, target])

    source_files = {f.name: f for f in found.get(source, [])}
    target_files = {f.name: f for f in found.get(target, [])}

    changes: list[dict[str, Any]] = []
    for file_name, source_path in source_files.items():
        if file_name not in target_files:
            continue
        target_path = target_files[file_name]
        source_flat = flatten(load_config(source_path))
        target_flat = flatten(load_config(target_path))

        for key, value in sorted(source_flat.items()):
            if key not in target_flat:
                if is_secret_key(key, secret_pattern) and not args.include_secrets:
                    continue
                changes.append({"file": file_name, "key": key, "value": value})

    if not changes:
        print("No missing keys to apply.")
        return 0

    print("The following changes will be applied:")
    for change in changes:
        print(f"  {change['file']}: {change['key']} = {change['value']}")

    if not args.yes:
        response = input("Proceed? [y/N] ").strip().lower()
        if response != "y":
            print("Aborted.")
            return 0

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
            writer = WRITERS.get(ext)
            if writer:
                writer(target_path, target_config)
            else:
                print(f"Warning: Cannot write {ext} format, skipping {target_path}")

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
    if args.secret_pattern:
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
