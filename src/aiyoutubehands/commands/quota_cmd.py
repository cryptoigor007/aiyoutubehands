"""quota commands."""

from __future__ import annotations

import json
from pathlib import Path

import click


def register(cli: click.Group) -> None:
    @cli.group()
    def quota() -> None:
        """Квоты YouTube API."""

    @quota.command("status")
    @click.option("--db", default=None)
    @click.option("--limit", default=10000, type=int)
    @click.option("--json", "as_json", is_flag=True)
    def quota_status(db: str | None, limit: int, as_json: bool) -> None:
        """Текущее использование квоты."""
        from aiyoutubehands.config import get_state_dir
        from aiyoutubehands.quota import QuotaEngine

        path = Path(db) if db else get_state_dir() / "quota.db"
        eng = QuotaEngine(db_path=path, daily_limit=limit)
        used = eng.used_today()
        rem = eng.remaining()
        data = {"used": used, "remaining": rem, "limit": limit}
        if as_json:
            click.echo(json.dumps(data, ensure_ascii=False))
        else:
            click.echo(f"Использовано: {used} / {limit}")
            click.echo(f"Осталось: {rem}")
