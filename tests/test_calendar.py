"""Tests for publication calendar."""

from __future__ import annotations

from pathlib import Path

from aiyoutubehands.calendar import Calendar, CalendarEntry


def test_add_and_list(tmp_path: Path) -> None:
    cal = Calendar(tmp_path / "cal.db")
    e = CalendarEntry(
        video_id="v1",
        title="Test",
        publish_at="2026-10-01T12:00:00Z",
        status="scheduled",
    )
    cal.add(e)
    items = cal.list_entries()
    assert len(items) == 1
    assert items[0].video_id == "v1"
    assert items[0].title == "Test"


def test_update_status(tmp_path: Path) -> None:
    cal = Calendar(tmp_path / "cal.db")
    cal.add(CalendarEntry(video_id="v2", title="T", publish_at="2026-10-02T10:00:00Z"))
    cal.update_status("v2", "published")
    e = cal.get("v2")
    assert e is not None
    assert e.status == "published"


def test_delete(tmp_path: Path) -> None:
    cal = Calendar(tmp_path / "cal.db")
    cal.add(CalendarEntry(video_id="v3", title="X", publish_at="2026-10-03T00:00:00Z"))
    cal.delete("v3")
    assert cal.get("v3") is None


def test_ascii_grid(tmp_path: Path) -> None:
    cal = Calendar(tmp_path / "cal.db")
    cal.add(CalendarEntry(video_id="v1", title="A", publish_at="2026-10-05T12:00:00Z", status="scheduled"))
    grid = cal.ascii_grid(year=2026, month=10)
    assert "2026-10" in grid or "Окт" in grid or "10" in grid
    assert "A" in grid or "v1" in grid


def test_reject_empty_video_id(tmp_path: Path) -> None:
    cal = Calendar(tmp_path / "cal.db")
    try:
        cal.add(CalendarEntry(video_id="  ", title="T", publish_at="2026-10-01T00:00:00Z"))
        raise AssertionError("should have raised")
    except ValueError:
        pass
