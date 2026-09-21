# Contributing

Thanks for helping. SpecGuard has one rule that outranks the rest: **never report PASS for something that was not tested.** Changes that blur the line between PASS and UNVERIFIED will not be merged.

## Set up

```bash
git clone https://github.com/seun-john/specguard && cd specguard
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev]"                          # or: uv sync --extra dev
```

## Before you open a pull request

```bash
ruff check src tests examples
ruff format --check src tests examples
mypy
pytest --cov=specguard
```

CI runs the same commands on Python 3.10 to 3.13.

## Guidelines

- Keep parsing, rules, auditing, reporting, the CLI and MCP separate. Front ends call `specguard.api`; they do not contain rule logic.
- A new checker needs: parameter validation that rejects unknown names, evidence on every FAIL (`expected`, `actual`, `evidence`, `locations` where possible), and tests for pass, fail and invalid parameters.
- Extraction changes need tests for the sentence you are adding **and** a test that a nearby subjective sentence stays non-deterministic. Prefer leaving a sentence `semantic` over guessing a rule.
- Treat documents and specifications as untrusted input. No `eval`, no unsafe YAML, no network calls, no writing to audited files.
- Comments explain why, not what.
- Add a line to `CHANGELOG.md` under "Unreleased".

## Reporting bugs

Include the specification, a small document that reproduces the problem (or its text), the command, and the output. Please remove private content first.
