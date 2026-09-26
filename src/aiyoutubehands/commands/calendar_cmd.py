"""calendar commands."""

from __future__ import annotations

import json
from pathlib import Path

import click


def register(cli: click.Group) -> None:
    @cli.group()
    def calendar() -> None:
        """Календарь публикаций."""

    @calendar.command("list")
    @click.option("--db", default=None, help="Путь к SQLite БД")
    @click.option("--json", "as_json", is_flag=True)
    def calendar_list(db: str | None, as_json: bool) -> None:
        """Список записей календаря."""
        from aiyoutubehands.calendar import Calendar
        from aiyoutubehands.config import get_state_dir

        path = Path(db) if db else get_state_dir() / "calendar.db"
        cal = Calendar(path)
        entries = cal.list_entries()
        if as_json:
            click.echo(
                json.dumps(
                    [
                        {
                            "video_id": e.video_id,
                            "title": e.title,
                            "publish_at": e.publish_at,
                            "status": e.status,
                        }
                        for e in entries
                    ],
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            if not entries:
                click.echo("Календарь пуст")
                return
            for e in entries:
                click.echo(f"{e.publish_at}  [{e.status}]  {e.video_id}  {e.title}")

    @calendar.command("grid")
    @click.option("--year", type=int, default=2026)
    @click.option("--month", type=int, default=10)
    @click.option("--db", default=None)
    def calendar_grid(year: int, month: int, db: str | None) -> None:
        """ASCII-сетка календаря за месяц."""
        from aiyoutubehands.calendar import Calendar
        from aiyoutubehands.config import get_state_dir

        path = Path(db) if db else get_state_dir() / "calendar.db"
        cal = Calendar(path)
        click.echo(cal.ascii_grid(year, month))

    @calendar.command("add")
    @click.argument("video_id")
    @click.argument("title")
    @click.argument("publish_at")
    @click.option("--db", default=None)
    def calendar_add(video_id: str, title: str, publish_at: str, db: str | None) -> None:
        """Добавить запись в календарь."""
        from aiyoutubehands.calendar import Calendar, CalendarEntry
        from aiyoutubehands.config import get_state_dir

        path = Path(db) if db else get_state_dir() / "calendar.db"
        cal = Calendar(path)
        cal.add(CalendarEntry(video_id=video_id, title=title, publish_at=publish_at))
        click.echo(f"Добавлено: {video_id}")
