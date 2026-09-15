"""Shared fixtures for security tests — isolated temp storage."""

from __future__ import annotations

import pytest

from src.config import settings


@pytest.fixture
def temp_storage(tmp_path, monkeypatch):
    """Redirect all storage paths (profiles, SQLite db, chroma) to tmp_path."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    monkeypatch.setattr(settings, "data_dir", str(data_dir), raising=False)
    monkeypatch.setattr(settings, "profiles_dir", str(data_dir / "user_profiles"), raising=False)
    monkeypatch.setattr(settings, "db_path", str(data_dir / "polyglot.db"), raising=False)
    monkeypatch.setattr(settings, "chroma_path", str(data_dir / "chroma"), raising=False)

    return data_dir
