"""channel commands."""

from __future__ import annotations

import json
import sys

import click


def register(cli: click.Group) -> None:
    @cli.group()
    def channel() -> None:
        """Канал."""

    @channel.command("info")
    @click.option("--passphrase", default=None, envvar="AYH_TOKEN_PASSPHRASE")
    @click.option("--dry-run/--no-dry-run", default=True)
    @click.option("--json", "as_json", is_flag=True)
    def channel_info(passphrase: str | None, dry_run: bool, as_json: bool) -> None:
        if dry_run:
            data = {"dry_run": True, "message": "Нужен --no-dry-run + --passphrase"}
            click.echo(json.dumps(data, ensure_ascii=False) if as_json else "channel info: dry-run")
            return
        if not passphrase:
            sys.exit(2)
        from aiyoutubehands.service_factory import build_youtube_service

        yt, client = build_youtube_service(passphrase=passphrase)
        try:
            ch = yt.get_my_channel(dry_run=False)
        finally:
            client.close()
        if as_json:
            click.echo(
                json.dumps(
                    {
                        "id": ch.id,  # type: ignore[union-attr]
                        "title": ch.title,  # type: ignore[union-attr]
                        "subscribers": ch.subscriber_count,  # type: ignore[union-attr]
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            click.echo(f"{ch.id}: {ch.title} (subs={ch.subscriber_count})")  # type: ignore[union-attr]
