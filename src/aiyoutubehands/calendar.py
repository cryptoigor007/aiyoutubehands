"""Publication calendar (SQLite + ASCII grid + sync stub)."""

from __future__ import annotations

import calendar as calmod
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiyoutubehands.logging import get_logger

log = get_logger(__name__)

# Russian month names for user-facing grid
_MONTHS_RU = [
    "",
    "Янв",
    "Фев",
    "Мар",
    "Апр",
    "Май",
    "Июн",
    "Июл",
    "Авг",
    "Сен",
    "Окт",
    "Ноя",
    "Дек",
]


@dataclass
class CalendarEntry:
    video_id: str
    title: str
    publish_at: str  # ISO 8601
    status: str = "scheduled"  # scheduled | published | cancelled
    notes: str = ""

    def to_row(self) -> tuple[str, str, str, str, str]:
        return (self.video_id, self.title, self.publish_at, self.status, self.notes)

    @classmethod
    def from_row(cls, row: Any) -> CalendarEntry:
        return cls(
            video_id=row["video_id"],
            title=row["title"],
            publish_at=row["publish_at"],
            status=row["status"],
            notes=row["notes"] or "",
        )


class Calendar:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS entries (
                    video_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    publish_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'scheduled',
                    notes TEXT DEFAULT ''
                )
                """
            )

    def add(self, entry: CalendarEntry) -> None:
        if not entry.video_id.strip():
            raise ValueError("video_id не может быть пустым")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO entries (video_id, title, publish_at, status, notes)
                VALUES (?, ?, ?, ?, ?)
                """,
                entry.to_row(),
            )
        log.info("calendar_add", video_id=entry.video_id)

    def get(self, video_id: str) -> CalendarEntry | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM entries WHERE video_id = ?", (video_id,)).fetchone()
        return CalendarEntry.from_row(row) if row else None

    def list_entries(self, status: str | None = None) -> list[CalendarEntry]:
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM entries WHERE status = ? ORDER BY publish_at",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM entries ORDER BY publish_at").fetchall()
        return [CalendarEntry.from_row(r) for r in rows]

    def update_status(self, video_id: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE entries SET status = ? WHERE video_id = ?",
                (status, video_id),
            )
        log.info("calendar_status", video_id=video_id, status=status)

    def delete(self, video_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM entries WHERE video_id = ?", (video_id,))
        log.info("calendar_delete", video_id=video_id)

    def ascii_grid(self, year: int, month: int) -> str:
        """Build a simple ASCII month grid with entry titles."""
        entries = self.list_entries()
        by_day: dict[int, list[str]] = {}
        for e in entries:
            # publish_at like 2026-10-05T12:00:00Z
            try:
                parts = e.publish_at[:10].split("-")
                y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
                if y == year and m == month:
                    by_day.setdefault(d, []).append(e.title[:12] or e.video_id)
            except (ValueError, IndexError):
                continue

        month_name = _MONTHS_RU[month] if 1 <= month <= 12 else str(month)
        lines = [f"  {month_name} {year}", "Пн Вт Ср Чт Пт Сб Вс"]
        # Не меняем глобальное состояние модуля calendar: неделя с понедельника
        # задаётся локальным Calendar, иначе импорт библиотеки влиял бы на весь процесс.
        weeks = calmod.Calendar(firstweekday=calmod.MONDAY).monthdayscalendar(year, month)
        for week in weeks:
            cells = []
            for day in week:
                if day == 0:
                    cells.append("  .")
                else:
                    mark = "*" if day in by_day else " "
                    cells.append(f"{day:2d}{mark}")
            lines.append(" ".join(cells))
        # list entries under grid
        if by_day:
            lines.append("")
            for d in sorted(by_day):
                for t in by_day[d]:
                    lines.append(f"  {d:02d}: {t}")
        return "\n".join(lines)

    def sync_from_youtube_stub(self, videos: list[dict[str, Any]]) -> int:
        """Stub: accept list of {id, title, publish_at, status} and upsert."""
        count = 0
        for v in videos:
            self.add(
                CalendarEntry(
                    video_id=str(v.get("id") or ""),
                    title=str(v.get("title") or ""),
                    publish_at=str(v.get("publish_at") or ""),
                    status=str(v.get("status") or "scheduled"),
                )
            )
            count += 1
        return count
