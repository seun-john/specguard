<p align="center">
  <img src="assets/logo.png" alt="SpecGuard logo" width="420">
</p>

# SpecGuard

**Verify that AI-generated work actually follows the instructions.**

[![CI](https://github.com/seun-john/specguard/actions/workflows/ci.yml/badge.svg)](https://github.com/seun-john/specguard/actions/workflows/ci.yml)

AI generated the output. SpecGuard checks whether it followed the brief.

```text
$ specguard audit report.docx --spec specguard.yml

SPECGUARD AUDIT
  PASS         5
  FAIL         2
  UNVERIFIED   2

  Compliance among verified requirements: 77.8%
  Verification coverage: 77.8%

FAIL SG003  [major]
  Requirement: Do not use em dashes
  Expected: "—": none allowed
  Found: 6 occurrences
  Location: paragraph 5 (under "Background"); paragraph 8; paragraph 12
```


## The problem

You give an AI a brief: British English, no em dashes, under 3,000 words, all five objectives, keep the approved research questions word for word. It answers with fluent text and says it complied. Often it did not: a dash slipped in, a heading is missing, a research question was "improved".

SpecGuard does not trust the claim. It tests the output:

- Requirements that a program can check (word limits, forbidden text, required headings, exact wording) become rules and get a **PASS** or **FAIL** with evidence: what was expected, what was found, and where.
- Requirements that need judgement ("write in an engaging style") are kept, reported as **UNVERIFIED**, and never counted as passes.

SpecGuard is not an AI-content detector. It says nothing about who or what wrote the text. It checks instruction compliance only.

## Install

Requires Python 3.10 or newer.

```bash
pip install specguard
```

From a clone of this repository:

```bash
pip install -e ".[dev]"      # or: uv sync --extra dev
```

## 60-second quick start

Save your brief as `brief.txt`:

```text
Write a report between 1,500 and 2,000 words.
Do not use em dashes.
Include the sections Background, Findings, Recommendations and Conclusion.
Use the approved title exactly as supplied.
Write in a professional and engaging style.
```

Turn it into a specification, check it, then audit a document:

```bash
specguard extract brief.txt -o specguard.yml --explain
specguard validate specguard.yml
specguard audit report.docx --spec specguard.yml
```

`extract` finds seven testable rules (minimum words, maximum words, em dashes, four headings). It keeps the other two lines, marked `manual` (the approved title was not supplied, so there is nothing to compare) and `semantic` (the style requirement). Those two are reported UNVERIFIED.

To start from a blank template instead: `specguard init`.

## Specification format

A specification is a YAML file. Every requirement has an `id`, a `description`, and either a `checker` or a `verification_type` of `semantic`, `manual` or `unsupported`.

```yaml
version: 1
name: Example Thesis Requirements

requirements:
  - id: SG001
    description: Do not use em dashes
    category: style          # content, style, structure, count, formatting,
                             # terminology, preservation, file, semantic, other
    severity: major          # critical, major, minor, info
    checker: forbidden_punctuation
    parameters:
      marks: [em_dash]

  - id: SG002
    description: Document must not exceed 3000 words
    category: count
    severity: critical
    checker: word_count
    parameters:
      max: 3000
      exclude_sections: [References]

  - id: SG003
    description: Include a conclusion
    category: structure
    severity: major
    checker: required_section
    parameters:
      headings: [Conclusion]

  - id: SG004
    description: Preserve the approved research questions exactly
    category: preservation
    severity: critical
    checker: preserve_text
    parameters:
      baseline_file: approved_questions.txt   # must be inside this file's folder

  - id: SG005
    description: Write in an engaging academic style
    category: style
    severity: minor
    verification_type: semantic              # reported UNVERIFIED, never PASS
```

Optional fields: `source_text` (the original sentence), `weight` (overrides the severity weight), `enabled: false`, `notes`.

`specguard validate` reports every problem with its location, and suggests corrections for misspelt checker or parameter names. A misspelt parameter is an error, not something silently ignored, because a rule that tests nothing would otherwise pass.

Full reference: [docs/specification.md](docs/specification.md).

## CLI

| Command | What it does |
| --- | --- |
| `specguard init [PATH]` | Write a commented starter `specguard.yml`. |
| `specguard extract FILE [-o OUT] [--explain]` | Turn instructions into a specification. |
| `specguard validate SPEC` | Check a specification without auditing. |
| `specguard audit FILE --spec SPEC` | Audit a document. |
| `specguard rules [NAME]` | List checkers, or show one checker's parameters. |
| `specguard mcp` | Run the MCP server. |

`audit` options:

```bash
specguard audit report.docx --spec specguard.yml                  # terminal report
specguard audit report.md   --spec specguard.yml --format json
specguard audit report.md   --spec specguard.yml --format markdown -o audit.md
specguard audit report.md   --spec specguard.yml --format sarif   -o audit.sarif
specguard audit report.md   --fail-on critical                    # CI threshold
specguard audit report.md   --fail-on-unverified                  # also fail if anything was untested
```

Without `--spec`, SpecGuard reads `specguard.yml` in the current folder.

### Exit codes

| Code | Meaning |
| ---: | --- |
| 0 | Audit completed and no failure threshold was exceeded. |
| 1 | Compliance failure. |
| 2 | Invalid specification. |
| 3 | File or read error (missing, unreadable, unsupported type, malformed DOCX). |
| 4 | Internal error. |

`--fail-on` accepts `critical`, `major`, `minor`, `any` (default) and `none`. `any` fails on any FAIL or ERROR; advisory violations (`severity: info`) are WARNINGs and never fail the run. An ERROR (a checker that could not run) counts as a failure, because an untested requirement cannot be assumed to pass.

## Supported rules

| Checker | Checks |
| --- | --- |
| `word_count` | Minimum, maximum, exact or ranged length; can exclude sections such as References. |
| `forbidden_text` | Listed words or phrases must not appear. Case and whole-word options. |
| `required_text` | Listed words or phrases must appear (all, or any). |
| `forbidden_regex` / `required_regex` | Regular expressions, run under a timeout. |
| `occurrences` | A word, phrase or pattern must occur exactly / at least / at most / between N times. |
| `element_count` | Count bullets, numbered items, headings, tables, code blocks, paragraphs, references. |
| `required_section` | Named headings must exist; alternatives, exact or contains, case options. |
| `forbidden_punctuation` | Only the marks you list; optional `max_allowed`. |
| `preserve_text` | Protected text must appear unchanged; shows a word-level diff when it does not. |
| `file_type` | Expected file extension. |
| `docx_format` | Basic Word page setup: margins, orientation, default font, size, line spacing. |

Run `specguard rules <name>` for parameters. Details and edge cases: [docs/rules.md](docs/rules.md).

## Supported file types

`.txt`, `.md` and `.docx`. Each keeps paragraph numbers, headings and tables; text and Markdown also keep line numbers, so findings read like `line 72, paragraph 14` or `table 3, row 4`.

Not supported yet: PDF, PPTX, HTML, OCR. Word text boxes, headers, footers, footnotes and comments are not read. See [Limitations](#limitations).

## How requirement extraction works

`specguard extract` is a set of pattern matchers. It has no model and needs no network. It runs each clause through the matchers in order and keeps the first that recognises it:

| You write | It becomes |
| --- | --- |
| "at least 2000 words", "no more than 3000 words", "between 2,000 and 3,000 words" | `word_count` |
| "Do not use em dashes or semicolons" | `forbidden_punctuation` |
| `Avoid the word "very"` | `forbidden_text` |
| "Include a conclusion", "Include the sections A, B and C" | `required_section` |
| "Include at least 30 references", "Use exactly 5 bullet points" | `element_count` |
| "Mention climate change at least twice" | `occurrences` |
| `Preserve the following text exactly: "..."` | `preserve_text` |

Anything else that reads like an instruction is kept and classified, never guessed:

- `semantic`: needs language understanding ("Use British English", "Use strong academic reasoning").
- `manual`: needs a person, or the brief is ambiguous ("visually appealing", "a 1,500-word essay", "do not modify the research questions" with no text supplied).
- `unsupported`: testable in principle, but no checker exists yet (page limits, fonts, APA).

"Keep it below 3,000 words" is read strictly: at most 2,999. Review the output before relying on it; `--explain` shows how each sentence was read.

## Project checks: done, context, scope

Three commands audit a folder instead of one document. They use the same statuses as `audit` (PASS, FAIL, WARNING, UNVERIFIED) and exit with 1 on any FAIL.

**`specguard done`: is the work really finished?**

```bash
specguard done record -o test-record.json -- python -m pytest -q   # runs the command itself
specguard done check done.yml --root .
```

```yaml
# done.yml
files:
  - path: dist/report.docx          # must exist and be non-empty
  - path: data/results.json
    format: json                    # must parse
    sha256: 3b1f...                 # optional exact hash
scan_files: [src/app.py]            # TODO, FIXME, NotImplementedError and skip markers warn
criteria:
  - text: Output matches the approved template
    evidence_files: [docs/template-check.md]   # evidence exists, but a person must judge it
test_record: test-record.json
```

`record` runs your test command (no shell) and stores its exit code, parsed pass/fail/skip counts, timings and a hash of every file in the folder. `check` then refuses to call the tests passing when the record is stale (a file changed since), was edited, shows failures, or has no readable test counts. Without a record the result is UNVERIFIED, never PASS. The record is tamper-evident, not tamper-proof: anyone who can write to the folder can forge both the record and its hash.

**`specguard context`: are the agent instructions consistent?**

```bash
specguard context --root . --target src/api
```

Finds `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `.cursorrules` and Copilot instruction files that apply to the target folder, then reports duplicate rules, always/never contradictions (including "must", "do not" and "don't"), files over 16,000 characters, `@file` imports that do not exist, and lines that tell an agent to disclose credentials. It matches literal wording, so paraphrased contradictions are not found.

**`specguard scope`: did the change stay in bounds?**

```bash
specguard scope snapshot -o ../baseline.json
# ... the work happens ...
specguard scope check ../baseline.json --allow "src/*" --protect "approved/*"
```

Lists every added, modified and deleted file and marks each as allowed, outside the scope or protected. Dependency files such as `package.json` and `pyproject.toml` get an extra warning. Patterns use `fnmatch` (`*` also crosses `/`); a pattern ending in `/` covers a folder. Keep the baseline outside the folder.

## PASS, FAIL, WARNING, UNVERIFIED, ERROR

| Status | Meaning |
| --- | --- |
| PASS | Tested and satisfied. |
| FAIL | Tested and violated. Always comes with evidence. |
| WARNING | Tested, and not a clear violation: an advisory (`severity: info`) breach. |
| UNVERIFIED | Not tested: subjective, manual or unsupported. Never a pass. |
| ERROR | The checker itself failed, so nothing is known. |

## Compliance score versus verification coverage

Two numbers, kept apart on purpose.

- **Compliance among verified requirements**: the weighted share of *tested* requirements that passed. Weights come from severity (critical 8, major 4, minor 2, info 1) or an explicit `weight`. PASS earns full weight, WARNING half, FAIL none. UNVERIFIED and ERROR requirements are left out, so they cannot raise the score.
- **Verification coverage**: tested requirements divided by all enabled requirements.

```text
Total requirements: 25   Machine-verifiable: 18   Semantic/manual: 7
Compliance among verified requirements: 83%
Verification coverage: 72%
```

If nothing was tested, both are shown as "n/a", not 100%. The raw counts are always reported too.

## Use it in CI

```yaml
- run: pip install specguard
- run: specguard audit dist/report.md --spec specguard.yml --format sarif -o specguard.sarif
- uses: github/codeql-action/upload-sarif@v3
  if: always()
  with:
    sarif_file: specguard.sarif
```

The step fails the job on exit code 1. SARIF output maps each FAIL, WARNING and ERROR to a result with the rule id, severity, evidence and location. UNVERIFIED requirements are listed under `run.properties`, not as findings. DOCX files have no line numbers, so their results carry a logical location (`paragraph 14`) and `startLine: 1`.

## MCP server

SpecGuard ships an MCP server built on the official `mcp` Python SDK v2 (`mcp.server.mcpserver.MCPServer`). It calls the same core as the CLI.

```bash
specguard mcp                                   # stdio, may read files under the current folder
specguard mcp --root ./docs --root ./briefs     # allow specific folders
specguard mcp --transport streamable-http --port 8000   # http://127.0.0.1:8000/mcp
```

Claude Desktop or any stdio client:

```json
{
  "mcpServers": {
    "specguard": {
      "command": "specguard",
      "args": ["mcp", "--root", "/path/to/your/documents"]
    }
  }
}
```

| Tool | Purpose |
| --- | --- |
| `extract_requirements(instructions)` | Instructions to candidate requirements. |
| `validate_specification(specification)` | Validate a specification given as JSON. |
| `audit_text(content, specification, file_type)` | Audit text held in memory (`txt` or `md`). |
| `audit_file(file_path, specification_path)` | Audit a file. Paths must be inside a `--root`. |
| `compare_preserved_content(content, protected_text)` | Check protected wording, with a diff. |
| `list_supported_rules()` | Checkers and their parameters. |

Results are structured JSON. Failures come back as `{"ok": false, "error": {...}}` so a model can read the reason. Tools are marked read-only. Paths outside the allowed roots, including `..` and symlink escapes, are refused, and `baseline_file` may not point outside the specification's folder. The HTTP transport binds to `127.0.0.1` by default.

## Privacy and security

- SpecGuard is read-only. It never modifies the audited document or specification; it writes only the files you name with `--output`, `init` and `extract -o`, and it refuses to overwrite an existing file (or the input file) by accident.
- No document text is sent anywhere. The core needs no API key, no account and no network access.
- Specifications load with the safe YAML loader; anchors and aliases are refused. Regular expressions are length-limited and run under a timeout. Files over 25 MB are refused, and DOCX archives that would expand unreasonably are not opened. Malformed input yields a short error, not a traceback.
- Nothing inside an audited document is ever executed.

See [SECURITY.md](SECURITY.md).

## Limitations

- SpecGuard cannot judge subjective requirements: tone, style, spelling variety, argument quality. They are reported UNVERIFIED.
- Word counts are computed from the file and can differ from Word by a few percent. The default counts word tokens; `count_method: whitespace` is closer to Word. Page counts are not measured.
- The heading and reference detection is structural. In Markdown and DOCX a heading must be a real heading (`#` or a Word Heading style); bold text does not count. In plain text, a short standalone line is accepted with a note. `references` counts one entry per paragraph or list item under the reference-list heading.
- Extraction is conservative and English-only. It will miss instructions it does not recognise, and it needs the protected text to be supplied to test preservation.
- DOCX support covers paragraphs, headings, lists, tables and basic page setup. It is not a layout engine.
- Paragraph numbers in DOCX count non-empty body paragraphs in order, which can differ from Word's own numbering.

## Roadmap

Not implemented in 0.1.

- **0.2**: PPTX, PDF text inspection and HTML input; custom rule plugins; a GitHub Action.
- **0.3**: semantic verifier adapters (the `SemanticVerifier` interface exists, no implementation ships); optional local LLM verification; British/American English consistency; citation requirement checks.
- **Ecosystem**: companion tools for advanced Word layout, citation-to-claim checks, supervisor-comment compliance and writing-quality linting, consumed as extensions rather than built into the core.

## Extending SpecGuard

A new checker is one class and one decorator; the engine does not change. See [docs/architecture.md](docs/architecture.md).

```python
from specguard.rules import RuleChecker, register_rule

@register_rule
class NoShouting(RuleChecker):
    rule_type = "no_shouting"

    def check(self, document, requirement):
        shouted = [p.index for p in document.paragraphs if p.text.isupper()]
        if shouted:
            return self.failed(requirement, "Found shouting", evidence=[f"paragraph {i}" for i in shouted])
        return self.passed(requirement, "No shouting")
```

## Examples

Rule packs with sample documents are in [examples/](examples): `academic`, `business` and `coding`.

```bash
specguard audit examples/academic/draft.md --spec examples/academic/specguard.yml
specguard audit examples/business/quarterly_report.md --spec examples/business/specguard.yml
specguard audit examples/coding/README.example.md --spec examples/coding/specguard.yml
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

MIT. See [LICENSE](LICENSE).
