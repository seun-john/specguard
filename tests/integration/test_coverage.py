"""The shared coverage block: how much of the specification could be tested, and why not."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from tests.helpers import FIXTURES, md
from typer.testing import CliRunner

from specguard import api
from specguard.audit import AuditEngine
from specguard.audit.validation import parse_specification
from specguard.cli import app
from specguard.models.document import Document
from specguard.models.requirement import Requirement
from specguard.models.result import CheckResult, Coverage
from specguard.reports.json_report import report_to_dict
from specguard.rules import RuleChecker, RuleRegistry
from specguard.spec_yaml import dump_specification

runner = CliRunner()
GOOD = str(FIXTURES / "compliant_report.md")


def req(id_: str, **kw: Any) -> dict[str, Any]:
    return {"id": id_, "description": f"requirement {id_}", **kw}


MIXED = [
    req("A", checker="word_count", parameters={"max": 1000}),
    req("B", checker="forbidden_text", parameters={"values": ["TODO"]}),
    req("C", checker="forbidden_text", parameters={"values": ["lorem"]}, enabled=False),
    req("D", verification_type="semantic"),
    req("E", verification_type="semantic"),
    req("F", verification_type="manual"),
    req("G", verification_type="unsupported"),
]


def audit(requirements: list[dict[str, Any]], text: str = "A short clean document.") -> Any:
    spec = parse_specification({"requirements": requirements})
    return api.audit_document(spec, md(text))


class TestCoverageBlock:
    def test_counts_and_reasons_for_a_mixed_specification(self) -> None:
        coverage = audit(MIXED).coverage
        assert coverage is not None
        assert coverage.unit == "requirements"
        assert coverage.items == 6  # the disabled one is not an item
        assert coverage.decided == 2
        assert coverage.undecided == 4
        assert coverage.reasons == {"human_judgement": 1, "no_checker": 1, "semantic_judgement": 2}
        assert coverage.suppressed == 1

    def test_invariants_hold(self) -> None:
        coverage = audit(MIXED).coverage
        assert coverage is not None
        assert coverage.decided + coverage.undecided == coverage.items
        assert sum(coverage.reasons.values()) == coverage.undecided

    def test_a_failed_requirement_counts_as_decided(self) -> None:
        coverage = audit(MIXED[:2], "This has a TODO in it.").coverage
        assert coverage is not None
        assert (coverage.decided, coverage.undecided, coverage.reasons) == (2, 0, {})

    def test_a_checker_that_errors_is_undecided_with_its_own_reason(self) -> None:
        registry = RuleRegistry()

        @registry.register
        class Boom(RuleChecker):
            rule_type = "boom"

            def check(self, document: Document, requirement: Requirement) -> CheckResult:
                raise RuntimeError("kaput")

        spec = parse_specification({"requirements": [req("A", checker="boom")]}, registry=registry)
        report = AuditEngine(registry=registry).audit(spec, md("x"))
        assert report.coverage is not None
        assert report.coverage.reasons == {"checker_error": 1}
        assert (report.coverage.decided, report.coverage.undecided) == (0, 1)

    def test_no_requirements_means_no_share_not_a_perfect_one(self) -> None:
        assert Coverage(items=0, decided=0, undecided=0).decided_share is None
        assert Coverage(items=3, decided=1, undecided=2).decided_share == 33.3

    def test_describe_is_one_readable_line(self) -> None:
        line = audit(MIXED).coverage.describe()
        assert line == (
            "decided 2 of 6 requirements; 4 could not be checked "
            "(semantic_judgement 2, human_judgement 1, no_checker 1)"
        )

    def test_json_report_carries_the_block_and_keeps_existing_fields(self) -> None:
        data = report_to_dict(audit(MIXED))
        assert data["coverage"]["items"] == 6
        assert data["coverage"]["reasons"]["semantic_judgement"] == 2
        for old in ("summary", "entries", "notices", "specification_name", "document"):
            assert old in data


class TestReportsAndCli:
    def spec_file(self, tmp_path: Path, requirements: list[dict[str, Any]]) -> Path:
        path = tmp_path / "spec.yml"
        path.write_text(
            yaml.safe_dump({"version": 1, "requirements": requirements}), encoding="utf-8"
        )
        return path

    def test_terminal_and_markdown_reports_state_coverage(self, tmp_path: Path) -> None:
        spec = self.spec_file(tmp_path, MIXED)
        out = runner.invoke(app, ["audit", GOOD, "--spec", str(spec), "--fail-on", "none"]).stdout
        assert "decided 2 of 6 requirements; 4 could not be checked" in re.sub(r"\s+", " ", out)
        markdown = runner.invoke(
            app, ["audit", GOOD, "--spec", str(spec), "--fail-on", "none", "--format", "markdown"]
        ).stdout
        assert "- **Coverage:** decided 2 of 6 requirements" in markdown

    def test_min_coverage_exit_code(self, tmp_path: Path) -> None:
        spec = self.spec_file(tmp_path, MIXED)
        base = ["audit", GOOD, "--spec", str(spec), "--fail-on", "none", "--format", "json"]
        assert runner.invoke(app, [*base, "--min-coverage", "30"]).exit_code == 0
        assert runner.invoke(app, [*base, "--min-coverage", "50"]).exit_code == 5  # 2/6 = 33.3%
        assert runner.invoke(app, base).exit_code == 0  # opt-in

    def test_a_failure_wins_over_low_coverage(self, tmp_path: Path) -> None:
        spec = self.spec_file(
            tmp_path,
            [
                req("A", checker="word_count", parameters={"max": 1}),
                req("B", verification_type="manual"),
            ],
        )
        result = runner.invoke(app, ["audit", GOOD, "--spec", str(spec), "--min-coverage", "100"])
        assert result.exit_code == 1

    def test_nothing_tested_fails_min_coverage_rather_than_passing(self, tmp_path: Path) -> None:
        spec = self.spec_file(
            tmp_path, [req("A", checker="word_count", parameters={"max": 5}, enabled=False)]
        )
        result = runner.invoke(app, ["audit", GOOD, "--spec", str(spec), "--min-coverage", "1"])
        assert result.exit_code == 5

    def test_an_empty_specification_is_still_rejected_as_a_bad_spec(self, tmp_path: Path) -> None:
        spec = self.spec_file(tmp_path, [])
        result = runner.invoke(app, ["audit", GOOD, "--spec", str(spec), "--min-coverage", "1"])
        assert result.exit_code == 2

    @pytest.mark.parametrize("fmt", ["json", "markdown", "terminal"])
    def test_every_format_still_renders(self, fmt: str, tmp_path: Path) -> None:
        spec = self.spec_file(tmp_path, MIXED)
        result = runner.invoke(
            app, ["audit", GOOD, "--spec", str(spec), "--fail-on", "none", "--format", fmt]
        )
        assert result.exit_code == 0, result.output


INSTRUCTIONS = (
    "The report must have between 100 and 200 words. "
    "Do not use em dashes. "
    "Write in a warm, engaging tone. "
    "Thanks for reading this brief."
)


class TestNotExtracted:
    def test_extract_keeps_the_sentences_it_could_not_turn_into_requirements(self) -> None:
        result = api.extract_from_text(INSTRUCTIONS)
        spec = api.specification_from_extraction(result, "Brief")
        assert spec.not_extracted == result.skipped
        assert spec.not_extracted, "expected at least one skipped sentence in the sample brief"

    def test_they_survive_the_yaml_round_trip_and_reach_the_audit_coverage(
        self, tmp_path: Path
    ) -> None:
        spec = api.specification_from_extraction(api.extract_from_text(INSTRUCTIONS), "Brief")
        path = tmp_path / "spec.yml"
        path.write_text(dump_specification(spec), encoding="utf-8")
        result = api.validate_file(path)
        assert result.ok, [str(i) for i in result.errors]
        assert result.spec is not None
        assert result.spec.not_extracted == spec.not_extracted
        report = api.audit_document(result.spec, md("Short text."))
        assert report.coverage is not None
        assert any("became no requirement" in n for n in report.coverage.notes)
        c = report.coverage  # they are notes, not items, so the invariants still hold
        assert c.decided + c.undecided == c.items == len(spec.requirements)

    def test_a_specification_without_the_field_still_loads(self) -> None:
        spec = parse_specification({"requirements": [req("A", verification_type="manual")]})
        assert spec.not_extracted == []
        assert api.audit_document(spec, md("x")).coverage.notes == []

    def test_extract_command_says_how_many_sentences_it_left_out(self, tmp_path: Path) -> None:
        brief = tmp_path / "brief.txt"
        brief.write_text(INSTRUCTIONS, encoding="utf-8")
        result = runner.invoke(app, ["extract", str(brief)])
        assert result.exit_code == 0
        assert "became no requirement" in result.output
        assert "not_extracted:" in result.stdout
