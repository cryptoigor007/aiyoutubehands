"""Version consistency."""

from __future__ import annotations

from pathlib import Path

from aiyoutubehands import __version__


def test_version_matches_file() -> None:
    root = Path(__file__).resolve().parents[1]
    file_ver = (root / "VERSION").read_text().strip()
    assert __version__ == file_ver
