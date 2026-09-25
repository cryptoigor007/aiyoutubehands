"""AI YouTube Hands  AI-first CLI for YouTube channel control."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("aiyoutubehands")
except PackageNotFoundError:
    __version__ = "0.1.0"

__all__ = ["__version__"]
