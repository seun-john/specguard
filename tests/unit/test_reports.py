"""JSON, Markdown, SARIF and terminal reports."""

from __future__ import annotations

import io
import json
from typing import Any

import pytest
from rich.console import Console
from tests.helpers import FIXTURES

from specguard.api import audit_file, audit_text
from specguard.models.result import AuditReport, Status
from specguard.reports import (
    FORMATS,
    render_json,
    render_markdown,
    render_report,
    render_sarif,
    render_terminal,
    render_terminal_text,
    report_to_sarif,
)


@pytest.fixture(scope="module")
def failing_report() -> AuditReport:
    return audit_file(FIXTURES / "noncompliant_report.md", FIXTURES / "valid_spec.yml")


@pytest.fixture(scope="module")
def passing_report() -> AuditReport:
    return audit_file(FIXTURES / "compliant_report.md", FIXTURES / "valid_spec.yml")


class TestJson:
    def test_structure(self, failing_report: AuditReport) -> None:
        data = json.loads(render_json(failing_report))
        assert data["schema_version"] == 1
        assert set(data) >= {
            "specguard_version",
            "generated_at",
            "specification_name",
            "document",
            "summary",
            "entries",
            "notices",
        }
        assert set(data["summary"]) >= {
            "total_requirements",
            "machine_verifiable",
            "semantic_or_manual",
            "counts",
            "verified",
            "failed_by_severity",
            "compliance_score",
            "unweighted_compliance",
            "verification_coverage",
        }
        entry = data["entries"][0]
        assert set(entry) == {"requirement", "result"}
        assert set(entry["result"]) >= {
            "requirement_id",
            "status",
            "message",
            "expected",
            "actual",
            "evidence",
            "locations",
            "checker",
            "confidence",
            "remediation_hint",
        }
        assert entry["requirement"]["id"] == entry["result"]["requirement_id"]

    def test_statuses_are_plain_strings(self, failing_report: AuditReport) -> None:
        data = json.loads(render_json(failing_report))
        assert {e["result"]["status"] for e in data["entries"]} <= {s.value for s in Status}

    def test_locations_are_structured(self, failing_report: AuditReport) -> None:
        data = json.loads(render_json(failing_report))
        em = next(e for e in data["entries"] if e["requirement"]["id"] == "SG002")
        assert em["result"]["locations"][0]["line"] == 5
        assert em["result"]["locations"][0]["paragraph"] is not None

    def test_non_ascii_is_not_escaped(self, failing_report: AuditReport) -> None:
        assert "—" in render_json(failing_report)

    def test_unverified_score_is_null_not_100(self) -> None:
        report = audit_text(
            "x",
            {
                "requirements": [
                    {"id": "A", "description": "engaging", "verification_type": "semantic"}
                ]
            },
        )
        data = json.loads(render_json(report))
        assert data["summary"]["compliance_score"] is None
        assert data["summary"]["verification_coverage"] == 0.0


class TestMarkdown:
    def test_sections_and_evidence(self, failing_report: AuditReport) -> None:
        md = render_markdown(failing_report)
        assert md.startswith("# SpecGuard audit")
        assert (
            "## Fail (" in md
            and "## Unverified (1)" in md
            and "## Passed" not in md.split("## Unverified")[0]
        )
        assert "### FAIL SG005 (critical)" in md
        assert "**Expected:**" in md and "**Found:**" in md
        assert "Compliance among verified requirements:" in md
        assert "Verification coverage:" in md
        assert "does not detect AI authorship" in md

    def test_passing_document_lists_passes(self, passing_report: AuditReport) -> None:
        md = render_markdown(passing_report)
        assert "## Passed (6)" in md
        assert "## Fail" not in md

    def test_pipe_in_text_does_not_break_the_layout(self) -> None:
        report = audit_text(
            "a | b",
            {
                "requirements": [
                    {
                        "id": "A",
                        "description": "no pipes",
                        "checker": "forbidden_text",
                        "parameters": {"values": ["|"]},
                    }
                ]
            },
        )
        assert "\\|" in render_markdown(report)

    def test_unverified_is_never_listed_as_passed(self, passing_report: AuditReport) -> None:
        md = render_markdown(passing_report)
        passed_block = md.split("## Passed")[1]
        assert "SG007" not in passed_block


class TestSarif:
    def test_is_structurally_valid(self, failing_report: AuditReport) -> None:
        sarif = json.loads(render_sarif(failing_report))
        assert sarif["version"] == "2.1.0"
        assert sarif["$schema"].endswith("sarif-2.1.0.json")
        (run,) = sarif["runs"]
        driver = run["tool"]["driver"]
        assert driver["name"] == "SpecGuard" and driver["version"]
        rule_ids = [r["id"] for r in driver["rules"]]
        assert len(rule_ids) == len(set(rule_ids))
        assert run["results"], "a failing document must produce results"
        for result in run["results"]:
            assert result["ruleId"] == rule_ids[result["ruleIndex"]]
            assert result["level"] in {"error", "warning", "note", "none"}
            assert result["message"]["text"]
            assert result["locations"]
            for loc in result["locations"]:
                phys = loc["physicalLocation"]
                assert phys["artifactLocation"]["uri"].endswith("noncompliant_report.md")
                assert phys["region"]["startLine"] >= 1

    def test_findings_map_rule_severity_and_evidence(self, failing_report: AuditReport) -> None:
        run = json.loads(render_sarif(failing_report))["runs"][0]
        by_rule = {r["ruleId"]: r for r in run["results"]}
        assert by_rule["SG005"]["level"] == "error"  # critical
        assert by_rule["SG006"]["level"] == "warning"  # minor
        assert by_rule["SG002"]["locations"][0]["physicalLocation"]["region"]["startLine"] == 5
        assert by_rule["SG002"]["properties"]["evidence"]
        assert "Expected" in by_rule["SG005"]["message"]["text"]

    def test_unverified_requirements_are_not_findings(self, failing_report: AuditReport) -> None:
        run = json.loads(render_sarif(failing_report))["runs"][0]
        assert "SG007" not in {r["ruleId"] for r in run["results"]}
        assert run["properties"]["unverifiedRequirements"] == ["SG007"]

    def test_passing_document_has_no_results(self, passing_report: AuditReport) -> None:
        assert report_to_sarif(passing_report)["runs"][0]["results"] == []

    def test_docx_locations_fall_back_to_a_logical_location(self, thesis_docx: Any) -> None:
        from specguard.api import audit_document
        from specguard.audit import parse_specification
        from specguard.extractors import load_document

        spec = parse_specification(
            {
                "requirements": [
                    {
                        "id": "A",
                        "description": "no em dash",
                        "checker": "forbidden_punctuation",
                        "parameters": {"marks": ["em_dash"]},
                    }
                ]
            }
        )
        report = audit_document(spec, load_document(thesis_docx))
        loc = json.loads(render_sarif(report))["runs"][0]["results"][0]["locations"][0]
        assert loc["physicalLocation"]["region"]["startLine"] == 1
        assert loc["logicalLocations"][0]["name"].startswith("paragraph ")


class TestTerminal:
    def test_layout(self, failing_report: AuditReport) -> None:
        text = render_terminal_text(failing_report)
        assert text.startswith("SPECGUARD AUDIT")
        for expected in (
            "CRITICAL FAILURES",
            "FAILURES",
            "UNVERIFIED (not tested)",
            "Compliance among verified requirements:",
            "Verification coverage:",
            "were not tested and are not counted as passes",
            "Expected:",
            "Found:",
            "Location:",
            "Evidence:",
        ):
            assert expected in text, expected

    def test_the_protected_text_failure_shows_expected_found_and_changes(
        self, failing_report: AuditReport
    ) -> None:
        text = render_terminal_text(failing_report)
        assert "What factors are associated with clinic attendance?" in text
        assert "What are the major factors associated with clinic attendance?" in text
        assert "{+are the major+}" in text

    def test_unverified_explains_why(self, failing_report: AuditReport) -> None:
        text = render_terminal_text(failing_report)
        assert "UNVERIFIED SG007" in text
        assert "needs semantic judgement" in text

    def test_passing_document_lists_what_passed(self, passing_report: AuditReport) -> None:
        text = render_terminal_text(passing_report)
        assert "PASSED" in text and "SG001" in text and "FAILURES" not in text

    def test_verbose_shows_evidence_for_passes(self, passing_report: AuditReport) -> None:
        quiet = render_terminal_text(passing_report)
        verbose = render_terminal_text(passing_report, verbose=True)
        assert "Expected:" not in quiet
        assert "Expected:" in verbose

    def test_document_text_that_looks_like_rich_markup_is_printed_literally(self) -> None:
        report = audit_text(
            "This has [bold red]markup[/bold red] inside.",
            {
                "requirements": [
                    {
                        "id": "A",
                        "description": "no markup",
                        "checker": "forbidden_text",
                        "parameters": {"values": ["[bold red]"]},
                    }
                ]
            },
        )
        text = render_terminal_text(report)
        assert "[bold red]markup[/bold red]" in text

    def test_colour_can_be_switched_off(self, passing_report: AuditReport) -> None:
        buffer = io.StringIO()
        render_terminal(
            passing_report, Console(file=buffer, no_color=True, force_terminal=True, width=100)
        )
        assert "\x1b[3" not in buffer.getvalue()  # no colour codes


class TestDispatcher:
    @pytest.mark.parametrize("fmt", FORMATS)
    def test_every_format_renders(self, fmt: str, failing_report: AuditReport) -> None:
        assert render_report(failing_report, fmt)

    def test_unknown_format(self, failing_report: AuditReport) -> None:
        with pytest.raises(ValueError, match="Unknown format"):
            render_report(failing_report, "pdf")
