"""The MCP server: tools call the shared core, file access is confined, stdio launches."""

from __future__ import annotations

import json
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, TypeVar

import anyio
import pytest
from mcp import Client, StdioServerParameters
from tests.helpers import FIXTURES

from specguard import api
from specguard.mcp.server import create_server
from specguard.reports import report_to_dict

T = TypeVar("T")

EXPECTED_TOOLS = {
    "extract_requirements",
    "validate_specification",
    "audit_text",
    "audit_file",
    "compare_preserved_content",
    "list_supported_rules",
}

SPEC: dict[str, Any] = {
    "name": "t",
    "requirements": [
        {
            "id": "A",
            "description": "no em dash",
            "checker": "forbidden_punctuation",
            "parameters": {"marks": ["em_dash"]},
        },
        {"id": "B", "description": "engaging", "verification_type": "semantic"},
    ],
}


def with_client(roots: list[Path], body: Callable[[Client], Awaitable[T]]) -> T:
    async def main() -> T:
        async with Client(create_server(roots)) as client:
            return await body(client)

    return anyio.run(main)


def call(tool: str, arguments: dict[str, Any], roots: list[Path] | None = None) -> dict[str, Any]:
    async def body(client: Client) -> dict[str, Any]:
        result = await client.call_tool(tool, arguments)
        assert not result.is_error
        assert isinstance(result.structured_content, dict)
        return result.structured_content

    return with_client(roots or [FIXTURES], body)


def strip_time(report: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in report.items() if k != "generated_at"}


class TestTools:
    def test_exposes_the_six_tools_with_read_only_hints(self) -> None:
        async def body(client: Client) -> Any:
            return (await client.list_tools()).tools

        tools = with_client([FIXTURES], body)
        assert {t.name for t in tools} == EXPECTED_TOOLS
        for tool in tools:
            assert tool.annotations is not None and tool.annotations.read_only_hint is True
            assert tool.description

    def test_extract_requirements(self) -> None:
        out = call(
            "extract_requirements",
            {"instructions": (FIXTURES / "instructions.txt").read_text(encoding="utf-8")},
        )
        assert out["ok"] is True
        kinds = [r["verification_type"] for r in out["specification"]["requirements"]]
        assert kinds.count("deterministic") == 7 and "semantic" in kinds and "manual" in kinds
        assert out["interpretations"][0]["id"] == "SG001"

    def test_validate_specification(self) -> None:
        assert call("validate_specification", {"specification": SPEC})["valid"] is True
        bad = call(
            "validate_specification",
            {
                "specification": {
                    "requirements": [{"id": "A", "description": "x", "checker": "wrod_count"}]
                }
            },
        )
        assert bad["valid"] is False
        assert "Did you mean 'word_count'" in bad["issues"][0]["message"]

    def test_audit_text_uses_the_same_engine_as_the_cli(self) -> None:
        content = "One — two."
        out = call("audit_text", {"content": content, "specification": SPEC})
        expected = report_to_dict(api.audit_text(content, SPEC))
        assert strip_time(out["report"]) == strip_time(expected)
        statuses = {e["requirement"]["id"]: e["result"]["status"] for e in out["report"]["entries"]}
        assert statuses == {"A": "FAIL", "B": "UNVERIFIED"}

    def test_audit_text_markdown_type(self) -> None:
        spec = {
            "requirements": [
                {
                    "id": "H",
                    "description": "h",
                    "checker": "required_section",
                    "parameters": {"headings": ["Intro"]},
                }
            ]
        }
        out = call(
            "audit_text", {"content": "# Intro\n\ntext", "specification": spec, "file_type": "md"}
        )
        assert out["report"]["entries"][0]["result"]["status"] == "PASS"

    def test_audit_text_with_an_invalid_specification_returns_the_reason(self) -> None:
        out = call(
            "audit_text",
            {
                "content": "x",
                "specification": {
                    "requirements": [{"id": "A", "description": "d", "checker": "nope"}]
                },
            },
        )
        assert out["ok"] is False
        assert out["error"]["code"] == "invalid_specification"
        assert "unknown checker" in out["error"]["issues"][0]["message"]

    def test_audit_text_refuses_baseline_files(self) -> None:
        spec = {
            "requirements": [
                {
                    "id": "P",
                    "description": "p",
                    "checker": "preserve_text",
                    "parameters": {"baseline_file": "protected_questions.txt"},
                }
            ]
        }
        out = call("audit_text", {"content": "x", "specification": spec})
        assert out["ok"] is False
        assert "specification file location" in out["error"]["issues"][0]["message"]

    def test_audit_file(self) -> None:
        out = call(
            "audit_file",
            {"file_path": "noncompliant_report.md", "specification_path": "valid_spec.yml"},
        )
        expected = report_to_dict(
            api.audit_file(FIXTURES / "noncompliant_report.md", FIXTURES / "valid_spec.yml")
        )
        got = strip_time(out["report"])
        want = strip_time(expected)
        got["document"]["path"] = want["document"]["path"] = "x"
        assert got == want

    def test_audit_file_with_absolute_paths_inside_the_root(self) -> None:
        out = call(
            "audit_file",
            {
                "file_path": str(FIXTURES / "compliant_report.md"),
                "specification_path": str(FIXTURES / "valid_spec.yml"),
            },
        )
        assert out["report"]["summary"]["counts"]["FAIL"] == 0

    def test_compare_preserved_content(self) -> None:
        out = call(
            "compare_preserved_content",
            {"content": "What are the factors?", "protected_text": "What factors?"},
        )
        assert out["result"]["status"] == "FAIL"
        assert out["result"]["expected"] == "What factors?"
        assert any("Changes:" in e for e in out["result"]["evidence"])

    def test_compare_preserved_content_accepts_a_list(self) -> None:
        out = call(
            "compare_preserved_content",
            {"content": "One.\n\nTwo.", "protected_text": ["One.", "Two."]},
        )
        assert out["result"]["status"] == "PASS"

    def test_list_supported_rules(self) -> None:
        out = call("list_supported_rules", {})
        names = {r["rule_type"] for r in out["rules"]}
        assert {"word_count", "preserve_text", "required_section", "forbidden_regex"} <= names


class TestFileAccessIsConfined:
    def test_path_outside_the_roots_is_refused(self, tmp_path: Path) -> None:
        secret = tmp_path / "secret.md"
        secret.write_text("# secret", encoding="utf-8")
        out = call("audit_file", {"file_path": str(secret), "specification_path": "valid_spec.yml"})
        assert out["ok"] is False and out["error"]["code"] == "path_not_allowed"

    def test_dot_dot_traversal_is_refused(self) -> None:
        out = call(
            "audit_file",
            {"file_path": "../../pyproject.toml", "specification_path": "valid_spec.yml"},
        )
        assert out["error"]["code"] == "path_not_allowed"

    def test_specification_outside_the_roots_is_refused(self, tmp_path: Path) -> None:
        spec = tmp_path / "s.yml"
        spec.write_text("requirements: []", encoding="utf-8")
        out = call(
            "audit_file", {"file_path": "compliant_report.md", "specification_path": str(spec)}
        )
        assert out["error"]["code"] == "path_not_allowed"

    def test_symlink_escape_is_refused(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "doc.md").write_text("# hi", encoding="utf-8")
        root = tmp_path / "root"
        root.mkdir()
        try:
            (root / "link.md").symlink_to(outside / "doc.md")
        except (OSError, NotImplementedError):
            pytest.skip("symlinks are not available here")
        (root / "spec.yml").write_text(
            "requirements:\n  - {id: A, description: d, verification_type: manual}\n",
            encoding="utf-8",
        )
        out = call(
            "audit_file", {"file_path": "link.md", "specification_path": "spec.yml"}, roots=[root]
        )
        assert out["error"]["code"] == "path_not_allowed"

    def test_baseline_file_cannot_escape_the_specification_folder(self, tmp_path: Path) -> None:
        (tmp_path / "secret.txt").write_text("classified words here", encoding="utf-8")
        root = tmp_path / "root"
        root.mkdir()
        (root / "doc.md").write_text("hello", encoding="utf-8")
        (root / "spec.yml").write_text(
            "requirements:\n  - id: P\n    description: p\n    checker: preserve_text\n"
            "    parameters: {baseline_file: ../secret.txt}\n",
            encoding="utf-8",
        )
        out = call(
            "audit_file",
            {"file_path": "doc.md", "specification_path": "spec.yml"},
            roots=[tmp_path],
        )
        assert out["ok"] is False
        assert "classified" not in json.dumps(out)

    def test_missing_file_is_a_structured_error_not_a_crash(self) -> None:
        out = call("audit_file", {"file_path": "nope.md", "specification_path": "valid_spec.yml"})
        assert out["ok"] is False and out["error"]["code"] == "file_error"

    def test_unexpected_errors_do_not_leak_details(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(*a: object, **k: object) -> None:
            raise RuntimeError("password=hunter2")

        monkeypatch.setattr(api, "audit_text", boom)
        out = call("audit_text", {"content": "x", "specification": SPEC})
        assert out["error"]["code"] == "internal_error"
        assert "hunter2" not in json.dumps(out)


class TestArchitecture:
    def test_mcp_layer_does_not_import_the_cli(self) -> None:
        import subprocess

        code = "import sys, specguard.mcp.server; print('specguard.cli' in sys.modules)"
        out = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, timeout=60
        )
        assert out.stdout.strip() == "False"

    def test_rule_logic_lives_only_in_the_core(self) -> None:
        source = (Path(api.__file__).parent / "mcp" / "server.py").read_text(encoding="utf-8")
        assert "specguard.rules" not in source and "AuditEngine" not in source
        assert "from specguard import" in source and "api." in source


class TestStdioLaunch:
    def test_server_starts_over_stdio_and_lists_tools(self, tmp_path: Path) -> None:
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "specguard", "mcp", "--root", str(FIXTURES)]
        )

        async def main() -> tuple[set[str], dict[str, Any]]:
            with anyio.fail_after(60):
                async with Client(params) as client:
                    tools = {t.name for t in (await client.list_tools()).tools}
                    result = await client.call_tool(
                        "audit_file",
                        {
                            "file_path": "compliant_report.md",
                            "specification_path": "valid_spec.yml",
                        },
                    )
                    assert isinstance(result.structured_content, dict)
                    return tools, result.structured_content

        tools, out = anyio.run(main)
        assert tools == EXPECTED_TOOLS
        assert out["report"]["summary"]["counts"]["PASS"] == 6
