"""Write a Specification as readable YAML, and the starter file for `specguard init`."""

from __future__ import annotations

import textwrap
from typing import Any

import yaml

from specguard.models.requirement import Requirement
from specguard.models.specification import Specification


def _requirement_dict(req: Requirement) -> dict[str, Any]:
    data: dict[str, Any] = {"id": req.id, "description": req.description}
    if req.source_text and req.source_text != req.description:
        data["source_text"] = req.source_text
    data["category"] = req.category.value
    data["severity"] = req.severity.value
    if req.verification_type is not None:
        data["verification_type"] = req.verification_type.value
    if req.checker:
        data["checker"] = req.checker
    if req.parameters:
        data["parameters"] = req.parameters
    if req.weight is not None:
        data["weight"] = req.weight
    if not req.enabled:
        data["enabled"] = False
    if req.notes:
        data["notes"] = req.notes
    return data


def dump_specification(spec: Specification, header: str = "") -> str:
    """YAML text for `spec`, with each requirement as a `- id:` block separated by blank lines."""
    out: list[str] = []
    if header:
        out += [f"# {line}".rstrip() for line in header.strip().splitlines()]
        out.append("")
    out.append("version: 1")
    out.append("name: " + yaml.safe_dump(spec.name, allow_unicode=True, width=1000).splitlines()[0])
    out.append("")
    out.append("requirements:")
    for req in spec.requirements:
        body = yaml.safe_dump(
            _requirement_dict(req),
            sort_keys=False,
            allow_unicode=True,
            width=100,
            default_flow_style=False,
        ).rstrip()
        out.append(textwrap.indent(body, "    ").replace("    ", "  - ", 1))
        out.append("")
    return "\n".join(out).rstrip() + "\n"


INIT_TEMPLATE = """\
# SpecGuard specification.
#
# Test a document against it:   specguard audit report.docx --spec specguard.yml
# Check this file for mistakes: specguard validate specguard.yml
# List the available checkers:  specguard rules
#
# Every requirement has an id, a description, a severity and either a `checker`
# (a rule SpecGuard can test) or a verification_type of semantic, manual or
# unsupported (SpecGuard reports those as UNVERIFIED and never as a pass).

version: 1
name: My document requirements

requirements:
  # Length: the document must not be longer than 3000 words.
  - id: SG001
    description: The document must not exceed 3000 words
    category: count
    severity: critical
    checker: word_count
    parameters:
      max: 3000
      # exclude_sections: [References]   # leave a section out of the count

  # Punctuation: only the marks you list are checked.
  - id: SG002
    description: Do not use em dashes
    category: style
    severity: major
    checker: forbidden_text
    parameters:
      values: ["—"]

  # Structure: these headings must exist.
  - id: SG003
    description: Include Introduction and Conclusion sections
    category: structure
    severity: major
    checker: required_section
    parameters:
      headings: [Introduction, Conclusion]

  # Wording: phrases that must never appear.
  - id: SG004
    description: No placeholder text
    category: content
    severity: major
    checker: forbidden_text
    parameters:
      values: [TODO, TBD, "lorem ipsum"]
      whole_word: true

  # A subjective requirement. SpecGuard cannot test it, so it is reported as
  # UNVERIFIED. It is never marked PASS.
  - id: SG005
    description: Write in a clear, engaging style
    category: style
    severity: minor
    verification_type: semantic

  # Protected text: it must appear exactly as given. Put the approved wording in
  # a file next to this one, then uncomment.
  #
  # - id: SG006
  #   description: Preserve the approved research questions exactly
  #   category: preservation
  #   severity: critical
  #   checker: preserve_text
  #   parameters:
  #     baseline_file: approved_questions.txt
"""
