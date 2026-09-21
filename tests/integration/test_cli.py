"""The command-line interface, exercised the way users and CI run it."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from tests.helpers import FIXTURES
from typer.testing import CliRunner, Result

from specguard import api
from specguard.cli import app

runner = CliRunner()
GOOD = str(FIXTURES / "compliant_report.md")
BAD = str(FIXTURES / "noncompliant_report.md")
SPEC = str(FIXTURES / "valid_spec.yml")


def run(*args: str) -> Result:
    return runner.invoke(app, list(args))


def digest(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class TestBasics:
    def test_help_lists_every_command(self) -> None:
        result = run("--help")
        assert result.exit_code == 0
        for command in ("init", "extract", "validate", "audit", "rules", "mcp"):
            assert command in result.stdout

    def test_no_arguments_shows_help(self) -> None:
        assert "Usage" in run().output

    def test_version(self) -> None:
        result = run("--version")
        assert result.exit_code == 0
        assert result.stdout.startswith("specguard 0.1.0")

    def test_audit_help_documents_exit_thresholds(self) -> None:
        out = run("audit", "--help").stdout
        assert "--fail-on" in out and "--format" in out and "--output" in out


class TestInit:
    def test_creates_a_valid_starter_specification(self, tmp_path: Path) -> None:
        target = tmp_path / "specguard.yml"
        result = run("init", str(target))
        assert result.exit_code == 0
        assert target.exists()
        assert run("validate", str(target)).exit_code == 0

    def test_starter_specification_audits_a_document(self, tmp_path: Path) -> None:
        target = tmp_path / "specguard.yml"
        run("init", str(target))
        result = run("audit", GOOD, "--spec", str(target), "--fail-on", "none")
        assert result.exit_code == 0
        assert "UNVERIFIED" in result.stdout  # the subjective sample rule

    def test_refuses_to_overwrite(self, tmp_path: Path) -> None:
        target = tmp_path / "specguard.yml"
        target.write_text("mine", encoding="utf-8")
        result = run("init", str(target))
        assert result.exit_code == 3
        assert target.read_text(encoding="utf-8") == "mine"
        assert run("init", str(target), "--force").exit_code == 0

    def test_example_file_in_repo_matches_the_template(self) -> None:
        from specguard.spec_yaml import INIT_TEMPLATE

        example = Path(__file__).parents[2] / "specguard.example.yml"
        assert example.read_text(encoding="utf-8") == INIT_TEMPLATE


class TestExtract:
    def test_prints_yaml_to_stdout(self) -> None:
        result = run("extract", str(FIXTURES / "instructions.txt"))
        assert result.exit_code == 0
        data = yaml.safe_load(result.stdout)
        assert data["version"] == 1
        assert [r["id"] for r in data["requirements"]][:2] == ["SG001", "SG002"]
        assert "7 testable, 2 that SpecGuard cannot test" in result.stderr

    def test_writes_a_file_that_validates(self, tmp_path: Path) -> None:
        out = tmp_path / "specguard.yml"
        result = run("extract", str(FIXTURES / "instructions.txt"), "-o", str(out))
        assert result.exit_code == 0
        assert run("validate", str(out)).exit_code == 0

    def test_explain_shows_how_each_line_was_read(self) -> None:
        result = run("extract", str(FIXTURES / "instructions.txt"), "--explain")
        assert "How each requirement was read" in result.stderr
        assert "semantic" in result.stderr and "manual" in result.stderr

    def test_subjective_line_is_kept_as_semantic(self) -> None:
        data = yaml.safe_load(run("extract", str(FIXTURES / "instructions.txt")).stdout)
        engaging = next(r for r in data["requirements"] if "engaging" in r["description"])
        assert engaging["verification_type"] == "semantic"
        assert "checker" not in engaging

    def test_refuses_to_overwrite_output(self, tmp_path: Path) -> None:
        out = tmp_path / "spec.yml"
        out.write_text("x", encoding="utf-8")
        assert run("extract", str(FIXTURES / "instructions.txt"), "-o", str(out)).exit_code == 3

    def test_missing_instructions_file(self, tmp_path: Path) -> None:
        assert run("extract", str(tmp_path / "nope.txt")).exit_code == 3

    def test_nothing_recognised_is_reported(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.txt"
        f.write_text("Just some background notes.", encoding="utf-8")
        result = run("extract", str(f))
        assert "No requirements were recognised" in result.stderr


class TestValidate:
    def test_valid(self) -> None:
        result = run("validate", SPEC)
        assert result.exit_code == 0
        assert "is valid: 7 requirement(s), 6 testable, 1 not testable" in result.stdout

    def test_invalid_exits_2_with_located_messages(self) -> None:
        result = run("validate", str(FIXTURES / "invalid_spec.yml"))
        assert result.exit_code == 2
        assert "requirements[1].severity" in result.stderr

    def test_missing_file_exits_3(self, tmp_path: Path) -> None:
        assert run("validate", str(tmp_path / "nope.yml")).exit_code == 3

    def test_malformed_yaml_exits_2(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.yml"
        f.write_text("requirements: [oops\n", encoding="utf-8")
        result = run("validate", str(f))
        assert result.exit_code == 2
        assert "invalid YAML" in result.stderr


class TestAudit:
    def test_compliant_document_exits_0(self) -> None:
        result = run("audit", GOOD, "--spec", SPEC)
        assert result.exit_code == 0
        assert "SPECGUARD AUDIT" in result.stdout
        assert "PASS" in result.stdout and "UNVERIFIED" in result.stdout
        assert "Verification coverage: 85.7%" in result.stdout

    def test_noncompliant_document_exits_1(self) -> None:
        result = run("audit", BAD, "--spec", SPEC)
        assert result.exit_code == 1
        assert "CRITICAL FAILURES" in result.stdout
        assert "What are the major factors" in result.stdout

    @pytest.mark.parametrize("fmt", ["json", "markdown", "sarif"])
    def test_formats_go_to_stdout_and_still_set_the_exit_code(self, fmt: str) -> None:
        result = run("audit", BAD, "--spec", SPEC, "--format", fmt)
        assert result.exit_code == 1
        if fmt == "markdown":
            assert result.stdout.startswith("# SpecGuard audit")
        else:
            json.loads(result.stdout)

    def test_json_is_pure_on_stdout(self) -> None:
        result = run("audit", BAD, "--spec", SPEC, "--format", "json")
        report = json.loads(result.stdout)
        assert report["summary"]["counts"]["FAIL"] == 6

    @pytest.mark.parametrize(
        ("fmt", "name"),
        [("json", "r.json"), ("markdown", "r.md"), ("sarif", "r.sarif"), ("terminal", "r.txt")],
    )
    def test_output_file(self, tmp_path: Path, fmt: str, name: str) -> None:
        out = tmp_path / name
        result = run("audit", BAD, "--spec", SPEC, "--format", fmt, "--output", str(out))
        assert result.exit_code == 1
        assert out.exists() and out.stat().st_size > 0
        assert f"Wrote {fmt} report" in result.stderr
        assert result.stdout == ""
        if fmt in ("json", "sarif"):
            json.loads(out.read_text(encoding="utf-8"))
        if fmt == "terminal":
            assert "\x1b[" not in out.read_text(encoding="utf-8")

    def test_fail_on_severity_thresholds(self, tmp_path: Path) -> None:
        spec = tmp_path / "s.yml"
        spec.write_text(
            "requirements:\n"
            "  - {id: A, description: minor thing, severity: minor, checker: word_count, parameters: {min: 1000}}\n",
            encoding="utf-8",
        )
        assert run("audit", GOOD, "--spec", str(spec)).exit_code == 1
        assert run("audit", GOOD, "--spec", str(spec), "--fail-on", "any").exit_code == 1
        assert run("audit", GOOD, "--spec", str(spec), "--fail-on", "major").exit_code == 0
        assert run("audit", GOOD, "--spec", str(spec), "--fail-on", "none").exit_code == 0

    def test_fail_on_unverified(self) -> None:
        assert run("audit", GOOD, "--spec", SPEC).exit_code == 0
        assert run("audit", GOOD, "--spec", SPEC, "--fail-on-unverified").exit_code == 1

    def test_missing_document_exits_3(self, tmp_path: Path) -> None:
        result = run("audit", str(tmp_path / "gone.md"), "--spec", SPEC)
        assert result.exit_code == 3
        assert "File not found" in result.stderr

    def test_unsupported_extension_exits_3(self, tmp_path: Path) -> None:
        f = tmp_path / "a.pdf"
        f.write_bytes(b"%PDF-1.4")
        result = run("audit", str(f), "--spec", SPEC)
        assert result.exit_code == 3
        assert "Unsupported file type" in result.stderr

    def test_malformed_docx_exits_3(self, tmp_path: Path) -> None:
        f = tmp_path / "broken.docx"
        f.write_bytes(b"not really a docx")
        assert run("audit", str(f), "--spec", SPEC).exit_code == 3

    def test_invalid_specification_exits_2_and_audits_nothing(self) -> None:
        result = run("audit", GOOD, "--spec", str(FIXTURES / "invalid_spec.yml"))
        assert result.exit_code == 2
        assert "Invalid specification" in result.stderr
        assert "PASS" not in result.stdout

    def test_missing_default_spec_points_to_init(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        result = run("audit", GOOD)
        assert result.exit_code == 3
        assert "specguard init" in result.stderr

    def test_uses_specguard_yml_in_the_current_folder_by_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        run("init")
        assert run("audit", GOOD, "--fail-on", "none").exit_code == 0

    def test_docx_document(self, thesis_docx: Path, tmp_path: Path) -> None:
        spec = tmp_path / "s.yml"
        spec.write_text(
            "requirements:\n"
            "  - {id: A, description: no em dash, checker: forbidden_punctuation, parameters: {marks: [em_dash]}}\n"
            "  - {id: B, description: sections, checker: required_section, parameters: {headings: [Introduction, Methodology, Conclusion]}}\n"
            "  - {id: C, description: no TBD, checker: forbidden_text, parameters: {values: [TBD]}}\n",
            encoding="utf-8",
        )
        result = run("audit", str(thesis_docx), "--spec", str(spec), "--format", "json")
        report = json.loads(result.stdout)
        status = {e["requirement"]["id"]: e["result"] for e in report["entries"]}
        assert status["A"]["status"] == "FAIL"
        assert (
            status["A"]["locations"][0]["paragraph"] == 4
        )  # title, heading, sentence, then this one
        assert status["B"]["status"] == "PASS"
        assert status["C"]["status"] == "FAIL"
        assert status["C"]["locations"][0]["table"] == 1
        assert report["document"]["file_type"] == "docx"

    def test_audit_never_modifies_its_inputs(self, thesis_docx: Path) -> None:
        before = [digest(p) for p in (GOOD, BAD, SPEC, thesis_docx)]
        for doc in (GOOD, BAD, str(thesis_docx)):
            run("audit", doc, "--spec", SPEC)
        assert [digest(p) for p in (GOOD, BAD, SPEC, thesis_docx)] == before

    def test_will_not_write_the_report_over_an_input(self, tmp_path: Path) -> None:
        doc = tmp_path / "doc.md"
        doc.write_text("# A\n\ntext", encoding="utf-8")
        result = run("audit", str(doc), "--spec", SPEC, "-o", str(doc))
        assert result.exit_code == 3
        assert doc.read_text(encoding="utf-8") == "# A\n\ntext"

    def test_unexpected_error_exits_4_without_a_traceback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(*a: object, **k: object) -> None:
            raise RuntimeError("secret internal detail: /home/user/key")

        monkeypatch.setattr(api, "audit_file", boom)
        monkeypatch.delenv("SPECGUARD_DEBUG", raising=False)
        result = run("audit", GOOD, "--spec", SPEC)
        assert result.exit_code == 4
        assert "Internal error" in result.stderr
        assert "Traceback" not in result.stderr
        assert "secret internal detail" not in result.stderr + result.stdout

    def test_rich_markup_in_paths_does_not_break_errors(self, tmp_path: Path) -> None:
        result = run("audit", str(tmp_path / "[bold]x.md"), "--spec", SPEC)
        assert result.exit_code == 3

    def test_no_color_flag(self) -> None:
        assert run("audit", GOOD, "--spec", SPEC, "--no-color").exit_code == 0


class TestRules:
    def test_lists_every_builtin(self) -> None:
        result = run("rules")
        assert result.exit_code == 0
        for name in (
            "word_count",
            "forbidden_text",
            "required_text",
            "forbidden_regex",
            "required_regex",
            "occurrences",
            "required_section",
            "forbidden_punctuation",
            "preserve_text",
            "file_type",
        ):
            assert name in result.stdout

    def test_parameters_for_one_checker(self) -> None:
        result = run("rules", "word_count")
        assert result.exit_code == 0
        assert "exclude_sections" in result.stdout

    def test_unknown_checker(self) -> None:
        assert run("rules", "nope").exit_code == 3


class TestAsRealProcess:
    """Runs the installed entry point in a subprocess, as a user or CI job would."""

    def env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.pop("PYTHONIOENCODING", None)  # emulate a default Windows console
        env.pop("PYTHONUTF8", None)
        return env

    def test_piped_output_survives_non_ascii_text(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-m", "specguard", "audit", BAD, "--spec", SPEC, "--no-color"],
            capture_output=True,
            env=self.env(),
            timeout=60,
        )
        assert proc.returncode == 1
        assert "—" in proc.stdout.decode("utf-8")
        assert proc.stderr == b""

    def test_json_from_a_subprocess_is_utf8(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-m", "specguard", "audit", BAD, "--spec", SPEC, "--format", "json"],
            capture_output=True,
            env=self.env(),
            timeout=60,
        )
        assert json.loads(proc.stdout.decode("utf-8"))["summary"]["total_requirements"] == 7

    def test_console_script_exists(self) -> None:
        script = Path(sys.executable).parent / ("specguard.exe" if os.name == "nt" else "specguard")
        assert script.exists()
        proc = subprocess.run([str(script), "--version"], capture_output=True, timeout=60)
        assert proc.returncode == 0
