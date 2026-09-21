from __future__ import annotations

from pathlib import Path

import pytest
from tests.helpers import build_docx


@pytest.fixture
def thesis_docx(tmp_path: Path) -> Path:
    """A small generated thesis-style DOCX (see tests/helpers.py)."""
    return build_docx(tmp_path / "thesis_sample.docx")
