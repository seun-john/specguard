"""Specification validation, the audit engine, scoring, thresholds and extensibility."""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import pytest
from tests.helpers import FIXTURES, md, txt

from specguard.api import audit_document, audit_text, compare_preserved, validate_data
from specguard.audit import AuditEngine, SemanticVerifier
from specguard.audit.policy import blocking_entries
from specguard.audit.scoring import compute_summary
from specguard.audit.validation import (
    load_specification,
    parse_specification,
    validate_specification_file,
)
from specguard.errors import FileAccessError
from specguard.models.document import Document
from specguard.models.requirement import Requirement, Severity, VerificationType
from specguard.models.result import AuditEntry, CheckResult, Status
from specguard.models.specification import Specification, SpecificationError
from specguard.rules import RuleChecker, RuleRegistry, default_registry, register_rule


def spec_of(*reqs: dict[str, Any], registry: RuleRegistry | None = None) -> Specification:
    return parse_specification({"requirements": list(reqs)}, registry=registry)


def req(id_: str, checker: str | None = None, **kw: Any) -> dict[str, Any]:
    return {"id": id_, "description": f"requirement {id_}", "checker": checker, **kw}


class TestValidation:
    def test_valid_file(self) -> None:
        result = validate_specification_file(FIXTURES / "valid_spec.yml")
        assert result.ok
        assert result.spec is not None
        assert len(result.spec.requirements) == 7

    def test_invalid_file_reports_every_problem_with_a_path(self) -> None:
        result = validate_specification_file(FIXTURES / "invalid_spec.yml")
        assert not result.ok
        messages = [str(i) for i in result.errors]
        # structure errors come first and stop deeper checks, so fix them, then re-run
        assert any("requirements[1].severity" in m for m in messages)

    def test_semantic_problems_are_all_listed_once_structure_is_fixed(self) -> None:
        result = validate_data(
            {
                "requirements": [
                    req("A", "word_cuont", parameters={"max": 1}),
                    req("A", "word_count", parameters={"maxx": 1}),
                    {"id": "C", "description": "d", "verification_type": "deterministic"},
                    req("D", "forbidden_regex", parameters={"pattern": "(unclosed"}),
                ]
            }
        )
        messages = [str(i) for i in result.errors]
        assert any(
            "unknown checker 'word_cuont'. Did you mean 'word_count'?" in m for m in messages
        )
        assert any("duplicate id 'A'" in m for m in messages)
        assert any("unknown parameter 'maxx'. Did you mean 'max'?" in m for m in messages)
        assert any("needs a checker" in m for m in messages)
        assert any("invalid regular expression" in m for m in messages)
        assert len(messages) == 5

    def test_malformed_yaml(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.yml"
        f.write_text("requirements: [unclosed\n  - x", encoding="utf-8")
        result = validate_specification_file(f)
        assert not result.ok
        assert "invalid YAML" in str(result.errors[0])
        assert "line" in str(result.errors[0])

    def test_yaml_aliases_are_refused(self, tmp_path: Path) -> None:
        f = tmp_path / "alias.yml"
        f.write_text("a: &x [1, 2]\nrequirements: *x\n", encoding="utf-8")
        assert "anchors and aliases" in str(validate_specification_file(f).errors[0])

    def test_yaml_cannot_construct_python_objects(self, tmp_path: Path) -> None:
        f = tmp_path / "evil.yml"
        f.write_text(
            "requirements: !!python/object/apply:os.system ['echo hi']\n", encoding="utf-8"
        )
        result = validate_specification_file(f)
        assert not result.ok  # rejected, and nothing was executed

    def test_empty_file(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.yml"
        f.write_text("", encoding="utf-8")
        assert "empty" in str(validate_specification_file(f).errors[0])

    def test_top_level_must_be_a_mapping(self) -> None:
        assert not validate_data(["a", "b"]).ok

    def test_unknown_top_level_field_is_named(self) -> None:
        result = validate_data(
            {"requirments": [], "requirements": [req("A", "word_count", parameters={"max": 1})]}
        )
        assert any("unknown field" in str(i) for i in result.errors)

    def test_missing_spec_file(self, tmp_path: Path) -> None:
        with pytest.raises(FileAccessError):
            validate_specification_file(tmp_path / "nope.yml")

    def test_no_requirements(self) -> None:
        assert any("no requirements" in str(i) for i in validate_data({"requirements": []}).errors)

    def test_invalid_id_characters(self) -> None:
        assert not validate_data({"requirements": [{"id": "bad id!", "description": "x"}]}).ok

    def test_unsupported_version(self) -> None:
        result = validate_data({"version": 2, "requirements": [{"id": "A", "description": "x"}]})
        assert any("version" in str(i) for i in result.errors)

    def test_checker_on_a_non_deterministic_requirement_warns(self) -> None:
        result = validate_data(
            {
                "requirements": [
                    req("A", "word_count", verification_type="manual", parameters={"max": 1})
                ]
            }
        )
        assert result.ok
        assert any("ignored" in str(w) for w in result.warnings)

    def test_load_specification_returns_base_dir(self) -> None:
        spec, base = load_specification(FIXTURES / "valid_spec.yml")
        assert base == FIXTURES.resolve()
        assert spec.name == "Community health report"

    def test_invalid_requirement_object(self) -> None:
        result = validate_data({"requirements": [{"description": "no id"}]})
        assert any("requirements[0].id" in str(i) for i in result.errors)


class TestEngine:
    def test_fixture_spec_on_compliant_and_noncompliant_documents(self) -> None:
        from specguard.api import audit_file

        good = audit_file(FIXTURES / "compliant_report.md", FIXTURES / "valid_spec.yml")
        by_id = {e.requirement.id: e.result.status for e in good.entries}
        assert by_id == {
            "SG001": Status.PASS,
            "SG002": Status.PASS,
            "SG003": Status.PASS,
            "SG004": Status.PASS,
            "SG005": Status.PASS,
            "SG006": Status.PASS,
            "SG007": Status.UNVERIFIED,
        }
        bad = audit_file(FIXTURES / "noncompliant_report.md", FIXTURES / "valid_spec.yml")
        by_id = {e.requirement.id: e.result.status for e in bad.entries}
        assert by_id["SG001"] is Status.FAIL  # too short
        assert by_id["SG002"] is Status.FAIL  # em dashes
        assert by_id["SG003"] is Status.FAIL  # no Conclusion
        assert by_id["SG004"] is Status.FAIL  # TODO
        assert by_id["SG005"] is Status.FAIL  # question changed
        assert by_id["SG006"] is Status.FAIL  # one reference
        assert by_id["SG007"] is Status.UNVERIFIED

    def test_every_failure_carries_evidence(self) -> None:
        from specguard.api import audit_file

        report = audit_file(FIXTURES / "noncompliant_report.md", FIXTURES / "valid_spec.yml")
        for entry in report.by_status(Status.FAIL):
            r = entry.result
            assert r.expected, entry.requirement.id
            assert r.actual, entry.requirement.id
            assert r.evidence, entry.requirement.id

    def test_subjective_requirements_are_never_a_pass(self) -> None:
        spec = spec_of(
            {
                "id": "S1",
                "description": "Write in an engaging academic style",
                "verification_type": "semantic",
            },
            {"id": "S2", "description": "Looks nice", "verification_type": "manual"},
            {"id": "S3", "description": "Page limit", "verification_type": "unsupported"},
            {"id": "S4", "description": "No checker and no type"},
        )
        report = audit_document(spec, txt("Anything at all."))
        assert [e.result.status for e in report.entries] == [Status.UNVERIFIED] * 4
        assert report.summary.compliance_score is None
        assert report.summary.verification_coverage == 0.0

    def test_semantic_message_explains_why(self) -> None:
        spec = spec_of({"id": "S1", "description": "Engaging", "verification_type": "semantic"})
        (entry,) = audit_document(spec, txt("x")).entries
        assert "semantic judgement" in entry.result.message
        assert "No semantic verifier is configured" in entry.result.message

    def test_disabled_requirements_are_skipped_and_counted(self) -> None:
        spec = spec_of(
            req("A", "word_count", parameters={"max": 1}, enabled=False),
            req("B", "word_count", parameters={"max": 5}),
        )
        report = audit_document(spec, txt("one two"))
        assert [e.requirement.id for e in report.entries] == ["B"]
        assert report.summary.disabled_requirements == 1

    def test_info_severity_violations_are_warnings_not_failures(self) -> None:
        spec = spec_of(req("A", "word_count", severity="info", parameters={"max": 1}))
        (entry,) = audit_document(spec, txt("one two three")).entries
        assert entry.result.status is Status.WARNING
        assert "advisory" in entry.result.message

    def test_invalid_spec_object_is_rejected_before_any_check_runs(self) -> None:
        bad = Specification(
            requirements=[
                Requirement(
                    id="A",
                    description="x",
                    checker="nope",
                    verification_type=VerificationType.DETERMINISTIC,
                )
            ]
        )
        with pytest.raises(SpecificationError):
            AuditEngine().audit(bad, txt("x"))

    def test_a_crashing_checker_becomes_an_error_and_the_audit_continues(self) -> None:
        registry = RuleRegistry()

        @registry.register
        class Boom(RuleChecker):
            rule_type = "boom"

            def check(self, document: Document, requirement: Requirement) -> CheckResult:
                raise RuntimeError("kaput")

        @registry.register
        class Fine(RuleChecker):
            rule_type = "fine"

            def check(self, document: Document, requirement: Requirement) -> CheckResult:
                return self.passed(requirement, "ok")

        spec = spec_of(req("A", "boom"), req("B", "fine"), registry=registry)
        report = AuditEngine(registry=registry).audit(spec, txt("x"))
        statuses = {e.requirement.id: e.result for e in report.entries}
        assert statuses["A"].status is Status.ERROR
        assert "RuntimeError: kaput" in statuses["A"].message
        assert "Traceback" not in statuses["A"].message
        assert statuses["B"].status is Status.PASS
        assert report.summary.counts["ERROR"] == 1

    def test_error_results_are_not_counted_as_verified(self) -> None:
        registry = RuleRegistry()

        @registry.register
        class Boom(RuleChecker):
            rule_type = "boom"

            def check(self, document: Document, requirement: Requirement) -> CheckResult:
                raise ValueError("x")

        report = AuditEngine(registry=registry).audit(
            spec_of(req("A", "boom"), registry=registry), txt("x")
        )
        assert report.summary.verified == 0
        assert report.summary.compliance_score is None

    def test_new_checker_needs_no_engine_change(self) -> None:
        @register_rule
        class NoShouting(RuleChecker):
            rule_type = "test_no_shouting"

            def check(self, document: Document, requirement: Requirement) -> CheckResult:
                shouted = [p.index for p in document.paragraphs if p.text.isupper()]
                if shouted:
                    return self.failed(
                        requirement, "Found shouting", evidence=[f"paragraph {i}" for i in shouted]
                    )
                return self.passed(requirement, "No shouting")

        try:
            report = audit_text("HELLO\n\nquiet", {"requirements": [req("X", "test_no_shouting")]})
            assert report.entries[0].result.status is Status.FAIL
            assert report.entries[0].result.checker == "test_no_shouting"
        finally:
            default_registry._checkers.pop("test_no_shouting")

    def test_duplicate_checker_names_are_refused(self) -> None:
        registry = RuleRegistry()

        @registry.register
        class A(RuleChecker):
            rule_type = "dup"

            def check(self, document: Document, requirement: Requirement) -> CheckResult:
                return self.passed(requirement, "")

        class B(A):
            pass

        with pytest.raises(ValueError, match="already registered"):
            registry.register(B)

    def test_checker_without_rule_type_is_refused(self) -> None:
        class Nameless(RuleChecker):
            def check(self, document: Document, requirement: Requirement) -> CheckResult:
                return self.passed(requirement, "")

        with pytest.raises(TypeError):
            RuleRegistry().register(Nameless)

    def test_empty_document_notice(self) -> None:
        report = audit_document(spec_of(req("A", "word_count", parameters={"max": 5})), txt(""))
        assert any("no text" in n for n in report.notices)

    def test_document_info_is_recorded(self, thesis_docx: Path) -> None:
        from specguard.extractors import load_document

        report = audit_document(
            spec_of(req("A", "word_count", parameters={"max": 5000})), load_document(thesis_docx)
        )
        assert report.document.file_type == "docx"
        assert report.document.headings == 6
        assert report.document.tables == 1
        assert report.document.path == str(thesis_docx)


class FakeVerifier(SemanticVerifier):
    name = "fake"

    def supports(self, requirement: Requirement) -> bool:
        return "British" in requirement.description

    def verify(self, document: Document, requirement: Requirement) -> CheckResult:
        colour = "color" in document.raw_text
        return CheckResult(
            requirement_id="ignored",
            status=Status.FAIL if colour else Status.PASS,
            message="American spelling found" if colour else "No American spellings seen",
            evidence=["found 'color'"] if colour else ["no US spellings from the list"],
            confidence=0.6,
        )


class TestSemanticVerifierSeam:
    spec: ClassVar[dict[str, Any]] = {
        "requirements": [
            {"id": "S1", "description": "Use British English", "verification_type": "semantic"},
            {"id": "S2", "description": "Be engaging", "verification_type": "semantic"},
        ]
    }

    def test_a_configured_verifier_can_judge_what_it_supports(self) -> None:
        report = audit_text("The color red.", self.spec, semantic_verifier=FakeVerifier())
        s1, s2 = (e.result for e in report.entries)
        assert s1.status is Status.FAIL
        assert s1.checker == "fake"
        assert s1.requirement_id == "S1"
        assert s2.status is Status.UNVERIFIED
        assert "No configured verifier supports this requirement" in s2.message

    def test_a_crashing_verifier_becomes_an_error(self) -> None:
        class Broken(FakeVerifier):
            def verify(self, document: Document, requirement: Requirement) -> CheckResult:
                raise ConnectionError("offline")

        report = audit_text("x", self.spec, semantic_verifier=Broken())
        assert report.entries[0].result.status is Status.ERROR

    def test_default_never_calls_anything_external(self) -> None:
        report = audit_text("x", self.spec)
        assert {e.result.status for e in report.entries} == {Status.UNVERIFIED}


class TestScoring:
    @staticmethod
    def entry(
        status: Status,
        severity: Severity = Severity.MAJOR,
        weight: float | None = None,
        vtype: VerificationType = VerificationType.DETERMINISTIC,
    ) -> AuditEntry:
        r = Requirement(
            id="X",
            description="x",
            severity=severity,
            weight=weight,
            verification_type=vtype,
            checker="word_count" if vtype is VerificationType.DETERMINISTIC else None,
        )
        return AuditEntry(
            requirement=r, result=CheckResult(requirement_id="X", status=status, message="")
        )

    def test_the_spec_example_shape(self) -> None:
        entries = (
            [self.entry(Status.PASS)] * 15
            + [self.entry(Status.FAIL)] * 3
            + [self.entry(Status.UNVERIFIED, vtype=VerificationType.SEMANTIC)] * 7
        )
        s = compute_summary(entries)
        assert (s.total_requirements, s.machine_verifiable, s.semantic_or_manual) == (25, 18, 7)
        assert s.verified == 18
        assert s.unweighted_compliance == pytest.approx(83.3, abs=0.05)
        assert s.verification_coverage == 72.0
        assert s.counts["PASS"] == 15 and s.counts["FAIL"] == 3 and s.counts["UNVERIFIED"] == 7

    def test_unverified_never_raises_the_score(self) -> None:
        base = compute_summary([self.entry(Status.PASS), self.entry(Status.FAIL)])
        more = compute_summary(
            [self.entry(Status.PASS), self.entry(Status.FAIL)]
            + [self.entry(Status.UNVERIFIED, vtype=VerificationType.SEMANTIC)] * 10
        )
        assert more.compliance_score == base.compliance_score
        assert more.verification_coverage is not None and base.verification_coverage is not None
        assert more.verification_coverage < base.verification_coverage

    def test_severity_weighting(self) -> None:
        s = compute_summary(
            [self.entry(Status.PASS, Severity.CRITICAL), self.entry(Status.FAIL, Severity.MINOR)]
        )
        assert s.compliance_score == pytest.approx(8 / 10 * 100)
        assert s.unweighted_compliance == 50.0

    def test_explicit_weight_overrides_severity(self) -> None:
        s = compute_summary([self.entry(Status.PASS, weight=1), self.entry(Status.FAIL, weight=3)])
        assert s.compliance_score == 25.0

    def test_warning_counts_half(self) -> None:
        assert compute_summary([self.entry(Status.WARNING)]).compliance_score == 50.0

    def test_nothing_verified_is_none_not_a_hundred(self) -> None:
        s = compute_summary([self.entry(Status.UNVERIFIED, vtype=VerificationType.MANUAL)])
        assert s.compliance_score is None and s.unweighted_compliance is None

    def test_no_requirements(self) -> None:
        s = compute_summary([])
        assert s.verification_coverage is None

    def test_failures_by_severity(self) -> None:
        s = compute_summary(
            [self.entry(Status.FAIL, Severity.CRITICAL), self.entry(Status.FAIL, Severity.MINOR)]
        )
        assert s.failed_by_severity == {"critical": 1, "major": 0, "minor": 1, "info": 0}


class TestPolicy:
    def report(self) -> Any:
        spec = spec_of(
            req("C", "word_count", severity="critical", parameters={"min": 100}),
            req("M", "word_count", severity="minor", parameters={"min": 100}),
            {"id": "U", "description": "vibes", "verification_type": "semantic"},
        )
        return audit_document(spec, txt("short"))

    @pytest.mark.parametrize(
        ("fail_on", "expected"),
        [
            ("critical", ["C"]),
            ("major", ["C"]),
            ("minor", ["C", "M"]),
            ("any", ["C", "M"]),
            ("none", []),
        ],
    )
    def test_thresholds(self, fail_on: str, expected: list[str]) -> None:
        assert [e.requirement.id for e in blocking_entries(self.report(), fail_on)] == expected

    def test_unverified_blocks_only_when_asked(self) -> None:
        assert "U" not in [e.requirement.id for e in blocking_entries(self.report(), "none")]
        blocked = blocking_entries(self.report(), "none", fail_on_unverified=True)
        assert [e.requirement.id for e in blocked] == ["U"]

    def test_bad_threshold_name(self) -> None:
        with pytest.raises(ValueError, match="fail_on"):
            blocking_entries(self.report(), "sometimes")


class TestCompare:
    def test_compare_preserved_wraps_the_same_rule(self) -> None:
        ok = compare_preserved("Keep this sentence.", "Keep this sentence.")
        assert ok.status is Status.PASS
        changed = compare_preserved("Keep that sentence.", ["Keep this sentence."])
        assert changed.status is Status.FAIL
        assert "{+that+}" in "\n".join(changed.evidence)

    def test_markdown_content(self) -> None:
        assert (
            compare_preserved(
                "# T\n\nKeep **this** sentence.", "Keep this sentence.", file_type="md"
            ).status
            is Status.PASS
        )


class TestMarkdownDocumentHelpers:
    def test_md_helper_sanity(self) -> None:
        assert md("# A").headings[0].text == "A"
