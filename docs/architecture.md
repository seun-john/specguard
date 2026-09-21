# Architecture

One core library serves every front end.

```text
           CLI                MCP server
            |                     |
            +----------+----------+
                       v
                specguard.api          (no printing, no exit codes)
                       |
   +---------+---------+---------+----------+
   v         v         v         v          v
extractors  rules     audit    reports   models
(parse)   (checkers) (engine) (render)   (data)
```

The CLI and the MCP server import `specguard.api` and nothing else from the core's logic. A test enforces that the MCP layer does not import the CLI and contains no rule logic.

| Package | Responsibility |
| --- | --- |
| `models` | `Requirement`, `CheckResult`, `Specification`, `Document`, `AuditReport`. |
| `extractors` | Bytes to `Document` (`txt`, `md`, `docx`), and prose to requirements (`instructions.py`). |
| `rules` | `RuleChecker` classes and the registry. |
| `audit` | `AuditEngine`, validation, scoring, failure policy, evidence formatting, `SemanticVerifier`. |
| `reports` | Terminal, JSON, Markdown and SARIF renderers. They never re-run a check. |
| `cli`, `mcp` | Thin front ends. |
| `utils` | Text helpers, safe regex, path guards, safe YAML. |

## Audit flow

1. Load and validate the specification (YAML, structure, checkers, parameters).
2. Load the document into a `Document`.
3. For each enabled requirement, by `verification_type`:
   - deterministic: build the checker from the registry and call `check(document, requirement)`;
   - semantic: ask the `SemanticVerifier` if one is configured, otherwise UNVERIFIED;
   - manual, unsupported: UNVERIFIED.
4. A checker that raises produces an ERROR entry with a short message; the audit continues.
5. Compute the summary and return an `AuditReport`.

## Adding a checker

```python
from specguard.rules import RuleChecker, register_rule

@register_rule
class MyRule(RuleChecker):
    rule_type = "my_rule"                    # the `checker:` name in a specification
    summary = "One line for `specguard rules`."
    parameter_help = {"limit": "What it means."}

    def parse(self, parameters):             # optional; raise ParameterError on bad input
        ...

    def check(self, document, requirement):
        return self.passed(requirement, "ok", evidence=["what you saw"])
```

`validate_parameters` (default: call `parse`) runs at validation time, so bad parameters are reported before any audit. Use `self.passed`, `self.failed` and `self.unverified` to build results; they fill in the requirement id, checker name and location cap. A FAIL should carry `expected`, `actual`, `evidence` and `locations`.

Use a private `RuleRegistry()` for tests or plugins that should not touch the default registry; pass it to `AuditEngine(registry=...)`.

Entry-point based plugin discovery is planned for 0.2. In 0.1, a plugin registers its checkers on import.

## Adding a file format

Subclass `DocumentExtractor`, set `file_type` and `extensions`, implement `extract(data, source) -> Document`, and call `register_extractor(MyExtractor())`. Populate `paragraphs`, `headings`, `tables` and `metadata`; rules work from those.

## Semantic verification

`SemanticVerifier` has two methods: `supports(requirement)` and `verify(document, requirement)`. Pass an instance to `AuditEngine(semantic_verifier=...)`. SpecGuard ships no implementation and never calls an external service itself. An implementation is responsible for what it sends where.

## Report schema

`AuditReport` (see `specguard.models.result`) is what `--format json` prints and what the MCP tools return. `schema_version` is 1. Scores are `null`, not 100, when nothing was verified.
