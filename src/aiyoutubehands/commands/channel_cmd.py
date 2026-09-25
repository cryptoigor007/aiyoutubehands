"""channel commands."""

from __future__ import annotations

import json
import sys

import click


def register(cli: click.Group) -> None:
    @cli.group()
    def channel() -> None:
        """Управление каналом (только чтение без подтверждения)."""

    @channel.command("info")
    @click.option("--dry-run/--no-dry-run", default=True, help="Без реального API")
    @click.option("--json", "as_json", is_flag=True)
    def channel_info(dry_run: bool, as_json: bool) -> None:
        """Информация о канале (dry-run по умолчанию)."""
        if dry_run:
            data = {
                "dry_run": True,
                "message": "Реальный запрос отключён (нужен --no-dry-run + токен)",
            }
            if as_json:
                click.echo(json.dumps(data, ensure_ascii=False))
            else:
                click.echo("channel info: dry-run (реальный API вызов отключён)")
            return
        click.echo("Реальный API вызов требует токен и подтверждение", err=True)
        sys.exit(2)
