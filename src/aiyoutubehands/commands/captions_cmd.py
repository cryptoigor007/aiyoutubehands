"""captions commands."""

from __future__ import annotations

import json

import click

from aiyoutubehands.commands.security import require_passphrase


def register(cli: click.Group) -> None:
    @cli.group()
    def captions() -> None:
        """Субтитры."""

    @captions.command("list")
    @click.argument("video_id")
    @click.option("--passphrase", default=None, help="Не рекомендуется: виден в истории команд")
    @click.option("--dry-run/--no-dry-run", default=True)
    @click.option("--json", "as_json", is_flag=True)
    def captions_list(video_id: str, passphrase: str | None, dry_run: bool, as_json: bool) -> None:
        if dry_run:
            click.echo(
                json.dumps({"dry_run": True, "video_id": video_id}, ensure_ascii=False)
                if as_json
                else f"captions list {video_id}: dry-run"
            )
            return
        passphrase = require_passphrase(passphrase)
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

    @captions.command("upload")
    @click.argument("video_id")
    @click.argument("file_path", type=click.Path(exists=True))
    @click.option("--language", default="ru")
    @click.option("--name", default="")
    @click.option("--passphrase", default=None, help="Не рекомендуется: виден в истории команд")
    @click.option("--yes", is_flag=True)
    @click.option("--dry-run/--no-dry-run", default=True)
    def captions_upload(
        video_id: str,
        file_path: str,
        language: str,
        name: str,
        passphrase: str | None,
        yes: bool,
        dry_run: bool,
    ) -> None:
        if dry_run or not yes:
            click.echo("dry-run / нужен --no-dry-run --yes")
            return
        passphrase = require_passphrase(passphrase)
        from aiyoutubehands.service_factory import build_youtube_service

        yt, client = build_youtube_service(passphrase=passphrase)
        try:
            assert client.access_token
            yt.upload_caption(
                video_id,
                file_path,
                language=language,
                name=name,
                access_token=client.access_token,
                dry_run=False,
                yes=True,
            )
        finally:
            client.close()
        click.echo("captions upload: OK")
