from __future__ import annotations

import os
from pathlib import Path

import pytest
from tests.helpers import build_docx

# CI systems often set FORCE_COLOR. The CLI builds its Rich consoles at import time and the
# tests assert on plain text, so colour is switched off before any test module imports it.
os.environ.pop("FORCE_COLOR", None)
os.environ["NO_COLOR"] = "1"
os.environ["TERM"] = "dumb"


@pytest.fixture
def thesis_docx(tmp_path: Path) -> Path:
    """A small generated thesis-style DOCX (see tests/helpers.py)."""
    return build_docx(tmp_path / "thesis_sample.docx")
