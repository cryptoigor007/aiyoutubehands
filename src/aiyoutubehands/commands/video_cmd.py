"""video commands."""

from __future__ import annotations

import json
import sys

import click


def register(cli: click.Group) -> None:
    @cli.group()
    def video() -> None:
        """Видео (только чтение / dry-run)."""

    @video.command("info")
    @click.argument("video_id")
    @click.option("--dry-run/--no-dry-run", default=True)
    @click.option("--json", "as_json", is_flag=True)
    def video_info(video_id: str, dry_run: bool, as_json: bool) -> None:
        """Информация о видео (dry-run по умолчанию)."""
        if dry_run:
            data = {"dry_run": True, "video_id": video_id}
            if as_json:
                click.echo(json.dumps(data, ensure_ascii=False))
            else:
                click.echo(f"video info {video_id}: dry-run")
            return
        click.echo("Реальный API требует токен", err=True)
        sys.exit(2)
