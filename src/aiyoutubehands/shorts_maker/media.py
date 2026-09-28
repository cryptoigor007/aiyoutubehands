"""Local media helpers (optional ffprobe for duration)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from aiyoutubehands.logging import get_logger

log = get_logger(__name__)


def probe_duration_seconds(path: Path | str) -> int | None:
    """Return media duration in whole seconds via ffprobe, or None if unavailable."""
    path = Path(path)
    if not path.is_file():
        return None
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        proc = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if proc.returncode != 0:
            log.warning("ffprobe_failed", path=str(path), stderr=proc.stderr[:200])
            return None
        data = json.loads(proc.stdout or "{}")
        fmt = data.get("format") if isinstance(data, dict) else None
        if not isinstance(fmt, dict):
            return None
        dur = fmt.get("duration")
        if isinstance(dur, bool) or not isinstance(dur, (str, int, float)):
            return None
        return int(round(float(dur)))
    except (
        OSError,
        subprocess.TimeoutExpired,
        ValueError,
        TypeError,
        json.JSONDecodeError,
    ) as exc:
        log.warning("ffprobe_error", path=str(path), error=str(exc))
        return None


def probe_is_vertical(path: Path | str) -> bool | None:
    """True if primary video stream is vertical (height > width). None if unknown."""
    path = Path(path)
    if not path.is_file():
        return None
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        proc = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if proc.returncode != 0:
            return None
        data = json.loads(proc.stdout or "{}")
        streams = data.get("streams") if isinstance(data, dict) else None
        if not isinstance(streams, list) or not streams:
            return None
        first = streams[0]
        if not isinstance(first, dict):
            return None
        w = int(first.get("width") or 0)
        h = int(first.get("height") or 0)
        if w <= 0 or h <= 0:
            return None
        return h > w
    except (OSError, subprocess.TimeoutExpired, ValueError, json.JSONDecodeError, TypeError):
        return None


def is_likely_short(path: Path | str, *, max_seconds: int = 60) -> bool | None:
    """Heuristic: duration ≤ max_seconds and vertical. None if cannot probe."""
    dur = probe_duration_seconds(path)
    if dur is None:
        return None
    if dur > max_seconds:
        return False
    vertical = probe_is_vertical(path)
    if vertical is None:
        return dur <= max_seconds  # duration-only fallback
    return vertical
