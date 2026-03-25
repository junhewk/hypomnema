"""Fixtures for scheduler tests."""

from pathlib import Path

import pytest


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Return the DB path used by tmp_db (for scheduler to open its own connections)."""
    return tmp_path / "test.db"
