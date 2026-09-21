# Specification reference

A specification is a YAML file: a name and a list of requirements.

```yaml
version: 1            # required to be 1 in this release
name: My requirements
description: Optional free text.
requirements: [...]
```

Unknown top-level fields are errors, so a typo such as `requirments:` is reported instead of ignored.

## Requirement fields

| Field | Required | Meaning |
| --- | --- | --- |
| `id` | yes | Stable identifier: letters, digits, `.`, `_`, `-`, up to 64 characters. Unique in the file. Used in reports and SARIF rule ids. |
| `description` | yes | What is required, in plain words. |
| `source_text` | no | The original sentence, if the rule came from prose. |
| `category` | no | `content`, `style`, `structure`, `count`, `formatting`, `terminology`, `preservation`, `file`, `semantic`, `other`. Default `other`. |
| `severity` | no | `critical`, `major` (default), `minor`, `info`. |
| `verification_type` | no | `deterministic`, `semantic`, `manual`, `unsupported`. If omitted: `deterministic` when a `checker` is named, otherwise `semantic`. |
| `checker` | if deterministic | A rule name from `specguard rules`. |
| `parameters` | no | Options for the checker. Unknown names are errors. |
| `weight` | no | Positive number. Overrides the severity weight in the compliance score. |
| `enabled` | no | `false` skips the requirement (it is counted in `summary.disabled_requirements`). |
| `notes` | no | Free text, shown as evidence when the requirement is UNVERIFIED. |

### Verification types

- `deterministic`: run the named checker.
- `semantic`: needs language understanding. UNVERIFIED unless the application supplies a `SemanticVerifier`.
- `manual`: needs a person. Always UNVERIFIED.
- `unsupported`: testable in principle, no checker yet. Always UNVERIFIED.

Naming a `checker` on a non-deterministic requirement is allowed (it is ignored, with a warning). This is how you park a rule without deleting it.

### Severity

Severity sets the default weight (critical 8, major 4, minor 2, info 1) and the `--fail-on` threshold. A violation of an `info` requirement is reported as WARNING and never fails a run.

## Protected text

`preserve_text` needs the text you want protected, either inline or in a file next to the specification:

```yaml
parameters:
  baseline_file: approved_questions.txt   # relative to this file; may not point outside its folder
  split: lines                            # lines (default) | paragraphs | whole
```

Each line (or paragraph) of the file must appear in the document exactly. When one does not, the report shows the expected text, the closest passage found, and a word-level diff using `[-removed-]` and `{+added+}`.

## Validation order

1. YAML syntax (safe loader, no anchors or aliases, 1 MB limit).
2. Structure: fields, types, enum values.
3. Meaning: duplicate ids, known checkers, valid parameters, readable baseline files.

Structure errors stop the later steps, so fix them and run `specguard validate` again.
