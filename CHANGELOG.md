# Changelog

All notable changes are recorded here. This project follows [Semantic Versioning](https://semver.org/); versions below 1.0 may change behaviour between minor releases.

## Unreleased

## 0.2.0

### Added

- `specguard done record` and `specguard done check`: run a test command and keep a tamper-evident record, then check that a folder's files, criteria and test record support a claim of completion. Stale, edited or count-less records fail.
- `specguard context`: lint AGENTS.md, CLAUDE.md, GEMINI.md, .cursorrules and Copilot instruction files for duplicates, contradictions, bloat, broken `@` imports and credential-disclosure instructions.
- `specguard scope snapshot` and `specguard scope check`: compare a folder with a hash baseline against allowed and protected path patterns.

## 0.1.0

First usable release.

### Added

- Audit engine that tests `.txt`, `.md` and `.docx` documents against a YAML specification and reports PASS, FAIL, WARNING, UNVERIFIED or ERROR with evidence and locations.
- Checkers: `word_count`, `forbidden_text`, `required_text`, `forbidden_regex`, `required_regex`, `occurrences`, `element_count`, `required_section`, `forbidden_punctuation`, `preserve_text`, `file_type`, `docx_format`.
- Separate compliance score (verified requirements only, severity weighted) and verification coverage. Both are `null` when nothing was verified.
- `specguard` CLI: `init`, `extract`, `validate`, `audit`, `rules`, `mcp`. Documented exit codes and `--fail-on` / `--fail-on-unverified`.
- Conservative natural-language extraction. Subjective, ambiguous or unsupported instructions are kept as `semantic`, `manual` or `unsupported` and reported UNVERIFIED.
- Terminal, JSON, Markdown and SARIF 2.1.0 reports.
- MCP server on the official Python SDK v2 (stdio and Streamable HTTP) with six read-only tools and folder confinement.
- `SemanticVerifier` interface for future semantic checks (no implementation ships).
- Registry-based checker and extractor extension points.
- Example rule packs for academic, business and coding documents.
