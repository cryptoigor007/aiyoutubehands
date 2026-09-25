"""AI YouTube Hands - AI-first CLI for YouTube channel control."""

from __future__ import annotations

from pathlib import Path

from importlib.metadata import PackageNotFoundError, version


def _version_from_file() -> str:
    """Read VERSION file next to package root (src/../VERSION)."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "VERSION"
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8").strip()
    return "0.1.0"


try:
    __version__ = version("aiyoutubehands")
except PackageNotFoundError:
    __version__ = _version_from_file()

__all__ = ["__version__"]
