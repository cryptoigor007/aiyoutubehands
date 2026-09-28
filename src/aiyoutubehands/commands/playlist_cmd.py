"""playlist commands."""

from __future__ import annotations

import json

import click

from aiyoutubehands.commands.security import require_passphrase


def register(cli: click.Group) -> None:
    @cli.group()
    def playlist() -> None:
        """Плейлисты."""

    @playlist.command("list")
    @click.option("--dry-run/--no-dry-run", default=True)
    @click.option("--json", "as_json", is_flag=True)
    def playlist_list(dry_run: bool, as_json: bool) -> None:
        if dry_run:
            click.echo(json.dumps({"dry_run": True}) if as_json else "playlist list: dry-run")
            return
        passphrase = require_passphrase(None)
        from aiyoutubehands.service_factory import build_youtube_service

        yt, client = build_youtube_service(passphrase=passphrase)
        try:
            items = yt.list_playlists(dry_run=False)
        finally:
            client.close()
        if as_json:
            click.echo(
                json.dumps(
                    [{"id": p.id, "title": p.title, "items": p.item_count} for p in items],  # type: ignore[union-attr]
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            for p in items:  # type: ignore[union-attr]
                click.echo(f"{p.id}  [{p.item_count}]  {p.title}")

    @playlist.command("create")
    @click.argument("title")
    @click.option("--description", default="")
    @click.option("--privacy", default="private")
    @click.option("--yes", is_flag=True)
    @click.option("--dry-run/--no-dry-run", default=True)
    def playlist_create(
        title: str,
        description: str,
        privacy: str,
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
            pl = yt.create_playlist(title, description, privacy, dry_run=False, yes=True)
        finally:
            client.close()
        click.echo(f"playlist create: {getattr(pl, 'id', pl)}")

    @playlist.command("add")
    @click.argument("playlist_id")
    @click.argument("video_id")
    @click.option("--yes", is_flag=True)
    @click.option("--dry-run/--no-dry-run", default=True)
    def playlist_add(
        playlist_id: str,
        video_id: str,
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
            yt.add_to_playlist(playlist_id, video_id, dry_run=False, yes=True)
        finally:
            client.close()
        click.echo("playlist add: OK")

    @playlist.command("delete")
    @click.argument("playlist_id")
    @click.option("--yes", is_flag=True)
    @click.option("--dry-run/--no-dry-run", default=True)
    def playlist_delete(playlist_id: str, yes: bool, dry_run: bool) -> None:
        if dry_run or not yes:
            click.echo("dry-run / нужен --no-dry-run --yes")
            return
        passphrase = require_passphrase(None)
        from aiyoutubehands.service_factory import build_youtube_service

        yt, client = build_youtube_service(passphrase=passphrase)
        try:
            yt.delete_playlist(playlist_id, dry_run=False, yes=True)
        finally:
            client.close()
        click.echo("playlist delete: OK")
