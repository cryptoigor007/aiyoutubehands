"""captions commands."""

from __future__ import annotations

import json
import sys

import click


def register(cli: click.Group) -> None:
    @cli.group()
    def captions() -> None:
        """Субтитры (captions)."""

    @captions.command("list")
    @click.argument("video_id")
    @click.option("--passphrase", default=None, envvar="AYH_TOKEN_PASSPHRASE")
    @click.option("--dry-run/--no-dry-run", default=True)
    @click.option("--json", "as_json", is_flag=True)
    def captions_list(
        video_id: str, passphrase: str | None, dry_run: bool, as_json: bool
    ) -> None:
        if dry_run:
            data = {"dry_run": True, "video_id": video_id}
            click.echo(json.dumps(data, ensure_ascii=False) if as_json else f"captions list {video_id}: dry-run")
            return
        if not passphrase:
            sys.exit(2)
        from aiyoutubehands.service_factory import build_youtube_service

        yt, client = build_youtube_service(passphrase=passphrase)
        try:
            items = yt.list_captions(video_id, dry_run=False)
        finally:
            client.close()
        if as_json:
            click.echo(
                json.dumps(
                    [{"id": c.id, "lang": c.language, "name": c.name} for c in items],  # type: ignore[union-attr]
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            for c in items:  # type: ignore[union-attr]
                click.echo(f"{c.id}  {c.language}  {c.name}")
