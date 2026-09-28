"""comments commands."""

from __future__ import annotations

import json

import click

from aiyoutubehands.commands.security import require_passphrase


def register(cli: click.Group) -> None:
    @cli.group()
    def comments() -> None:
        """Комментарии."""

    @comments.command("list")
    @click.argument("video_id")
    @click.option("--dry-run/--no-dry-run", default=True)
    @click.option("--json", "as_json", is_flag=True)
    def comments_list(video_id: str, dry_run: bool, as_json: bool) -> None:
        if dry_run:
            click.echo(
                json.dumps({"dry_run": True, "video_id": video_id}, ensure_ascii=False)
                if as_json
                else f"comments list {video_id}: dry-run"
            )
            return
        passphrase = require_passphrase(None)
        from aiyoutubehands.service_factory import build_youtube_service

        yt, client = build_youtube_service(passphrase=passphrase)
        try:
            items = yt.list_comment_threads(video_id, dry_run=False)
        finally:
            client.close()
        if not isinstance(items, list):
            click.echo(json.dumps(items, ensure_ascii=False, indent=2))
            return
        if as_json:
            click.echo(
                json.dumps(
                    [{"id": c.id, "author": c.author, "text": c.text} for c in items],
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            for c in items:
                click.echo(f"{c.id}  {c.author}: {c.text[:80]}")

    @comments.command("reply")
    @click.argument("parent_id")
    @click.argument("text")
    @click.option("--yes", is_flag=True)
    @click.option("--dry-run/--no-dry-run", default=True)
    def comments_reply(
        parent_id: str,
        text: str,
        yes: bool,
        dry_run: bool,
    ) -> None:
        if dry_run or not yes:
            click.echo("dry-run / нужен --no-dry-run --yes")
            return
        passphrase = require_passphrase(None)
        from aiyoutubehands.service_factory import build_youtube_service

        yt, client = build_youtube_service(passphrase=passphrase)
        try:
            yt.reply_to_comment(parent_id, text, dry_run=False, yes=True)
        finally:
            client.close()
        click.echo("comments reply: OK")

    @comments.command("moderate")
    @click.argument("comment_id")
    @click.argument("status", type=click.Choice(["heldForReview", "published", "rejected"]))
    @click.option("--yes", is_flag=True)
    @click.option("--dry-run/--no-dry-run", default=True)
    def comments_moderate(
        comment_id: str,
        status: str,
        yes: bool,
        dry_run: bool,
    ) -> None:
        if dry_run or not yes:
            click.echo("dry-run / нужен --no-dry-run --yes")
            return
        passphrase = require_passphrase(None)
        from aiyoutubehands.service_factory import build_youtube_service

        yt, client = build_youtube_service(passphrase=passphrase)
        try:
            yt.moderate_comment(comment_id, status, dry_run=False, yes=True)
        finally:
            client.close()
        click.echo("comments moderate: OK")
