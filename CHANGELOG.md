# Changelog

All notable changes to this project will be documented in this file.

## [0.1.1] - 2026-08-19

### Fixed
- File-level drift attribution (drift now per-file, not combined)
- int vs float type drift detection (no longer conflated)
- Boolean normalization (bool not conflated with int)
- Environment name validation (prevent path traversal)
- source/target validation in apply command (error if not found)
- Properties parser escape sequences (\n, \t, \=, \:, \\)
- YAML empty file handling (type check for non-dict root)
- find_config_files flat-structure fallback (regex boundary)

### Added
- CLI integration test for secret pattern
- CONTRIBUTING.md and CODE_OF_CONDUCT.md
- CHANGELOG.md
- [project.scripts] entrypoint in pyproject.toml
- Pinned ruff version in CI (0.5.0) to match pre-commit

## [0.1.0] - 2026-08-19

### Added
- Initial release
- Multi-format support (JSON, YAML, TOML, Java .properties)
- Drift detection (value drift, type drift, missing keys)
- Secret masking and safe apply mode
- Custom secret pattern flag
- Multiple output formats (Terminal, JSON, Markdown)
- CI/CD workflow with ruff linting and pytest
- Pre-commit hooks for local code quality
