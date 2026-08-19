# config-drift

**Detect configuration drift across environments.**

Zero-dependency CLI that compares configuration files across environments (like `dev/`, `staging/`, `prod/`), detects drift, and optionally applies safe non-secret changes.

## The Problem

> "Works locally, breaks in prod" because config files silently drift between environments.

## Quick Start

```bash
# Clone and run
git clone https://github.com/billybox1926-jpg/config-drift.git
cd config-drift

# Detect drift
python config_drift.py diff --configs-root ./examples/configs --environments dev,staging,prod

# Output as JSON
python config_drift.py diff --configs-root ./examples/configs --environments dev,prod --output-format json

# Output as Markdown report
python config_drift.py diff --configs-root ./examples/configs --environments dev,prod --output-format markdown --output drift.md

# Apply missing keys from dev to prod (safe mode, skips secrets)
python config_drift.py apply --configs-root ./examples/configs --source dev --target prod --yes
```

## Features

- **Zero dependencies** — Python 3.9+ stdlib only
- **Multiple formats** — JSON, YAML, TOML, Java `.properties`
- **Drift detection** — Missing keys, value drift, type drift
- **Secret masking** — Passwords and tokens are masked in reports
- **Safe apply** — Copy missing keys between environments (skips secrets by default)
- **Multiple outputs** — Terminal, JSON, Markdown
- **CI-friendly** — `--fail-on-drift` flag for automated checks

## Supported Formats

| Format | Extension | Parser |
|--------|-----------|--------|
| JSON | `.json` | stdlib `json` |
| Properties | `.properties` | custom parser |
| TOML | `.toml` | `tomllib` (3.11+) or `tomli` |
| YAML | `.yaml`, `.yml` | `PyYAML` (optional) |

YAML/TOML parsers are optional. If not installed, those files are skipped with a warning.

## CLI Usage

```
python config_drift.py diff --configs-root PATH --environments ENV1,ENV2 [--output-format terminal|json|markdown] [--output PATH] [--fail-on-drift]

python config_drift.py apply --configs-root PATH --source ENV --target ENV [--yes] [--include-secrets]
```

## Secret Detection

Default secret key pattern:
```
(password|passwd|pwd|secret|token|api[_-]?key|private[_-]?key|access[_-]?key|auth)
```

Case-insensitive. Secret values are masked as `***` in reports. In `apply` mode, secret keys are never copied unless `--include-secrets` is explicitly passed.

## Output Formats

### Terminal
```
CONFIG DRIFT REPORT
Configs root: ./configs
Environments: dev, staging, prod

File: app.json
  [VALUE DRIFT] db.host
    dev:      localhost
    staging:  db.staging.internal
    prod:     db.prod.internal
  [MISSING KEY] cache.enabled
    missing in: prod

Summary:
  Files compared: 2
  Drifts found:   4
  Missing keys:   1
```

### JSON
```json
{
  "configs_root": "./configs",
  "environments": ["dev", "staging", "prod"],
  "files": [...],
  "summary": {"files_compared": 2, "drifts_found": 4, "missing_keys": 1}
}
```

### Markdown
Supports GitHub-flavored Markdown with tables and code blocks.

## Examples

See the `examples/` directory for sample configurations and a drift report.

## License

MIT
