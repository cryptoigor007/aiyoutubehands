"""comments commands."""

from __future__ import annotations

import json
import sys

import click


def register(cli: click.Group) -> None:
    @cli.group()
    def comments() -> None:
        """Комментарии."""

    @comments.command("list")
    @click.argument("video_id")
    @click.option("--passphrase", default=None, envvar="AYH_TOKEN_PASSPHRASE")
    @click.option("--dry-run/--no-dry-run", default=True)
    @click.option("--json", "as_json", is_flag=True)
    def comments_list(
        video_id: str, passphrase: str | None, dry_run: bool, as_json: bool
    ) -> None:
        """Список comment threads."""
        if dry_run:
            data = {"dry_run": True, "video_id": video_id}
            click.echo(json.dumps(data, ensure_ascii=False) if as_json else f"comments list {video_id}: dry-run")
            return
        if not passphrase:
            click.echo("Нужен --passphrase")
            sys.exit(2)
        from aiyoutubehands.service_factory import build_youtube_service

        yt, client = build_youtube_service(passphrase=passphrase)
        try:
            items = yt.list_comment_threads(video_id, dry_run=False)
        finally:
            client.close()
        if as_json:
            click.echo(
                json.dumps(
                    [
                        {"id": c.id, "author": c.author, "text": c.text}
                        for c in items  # type: ignore[union-attr]
                    ],
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            for c in items:  # type: ignore[union-attr]
                click.echo(f"{c.id}  {c.author}: {c.text[:80]}")

    @comments.command("reply")
    @click.argument("parent_id")
    @click.argument("text")
    @click.option("--passphrase", default=None, envvar="AYH_TOKEN_PASSPHRASE")
    @click.option("--yes", is_flag=True)
    @click.option("--dry-run/--no-dry-run", default=True)
    def comments_reply(
        parent_id: str,
        text: str,
        passphrase: str | None,
        yes: bool,
        dry_run: bool,
    ) -> None:
        """Ответ на комментарий."""
        if dry_run or not yes:
            click.echo("dry-run / нужен --no-dry-run --yes")
            return
        if not passphrase:
            sys.exit(2)
        from aiyoutubehands.service_factory import build_youtube_service

        yt, client = build_youtube_service(passphrase=passphrase)
        try:
            yt.reply_to_comment(parent_id, text, dry_run=False, yes=True)
        finally:
            client.close()
        click.echo("comments reply: OK")
