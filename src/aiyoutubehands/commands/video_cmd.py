"""video commands."""

from __future__ import annotations

import json

import click

from aiyoutubehands.client import require_access_token
from aiyoutubehands.commands.security import require_passphrase


def register(cli: click.Group) -> None:
    @cli.group()
    def video() -> None:
        """Видео."""

    @video.command("info")
    @click.argument("video_id")
    @click.option("--passphrase", default=None, help="Не рекомендуется: виден в истории команд")
    @click.option("--dry-run/--no-dry-run", default=True)
    @click.option("--json", "as_json", is_flag=True)
    def video_info(video_id: str, passphrase: str | None, dry_run: bool, as_json: bool) -> None:
        if dry_run:
            data = {"dry_run": True, "video_id": video_id}
            click.echo(
                json.dumps(data, ensure_ascii=False)
                if as_json
                else f"video info {video_id}: dry-run"
            )
            return
        passphrase = require_passphrase(passphrase)
        from aiyoutubehands.service_factory import build_youtube_service

        yt, client = build_youtube_service(passphrase=passphrase)
        try:
            v = yt.get_video(video_id, dry_run=False)
        finally:
            client.close()
        if as_json:
            click.echo(
                json.dumps(
                    {
                        "id": v.id,  # type: ignore[union-attr]
                        "title": v.snippet.title,  # type: ignore[union-attr]
                        "privacy": v.status.privacy_status,  # type: ignore[union-attr]
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            click.echo(f"{v.id}: {v.snippet.title} [{v.status.privacy_status}]")  # type: ignore[union-attr]

    @video.command("publish")
    @click.argument("video_id")
    @click.option("--passphrase", default=None, help="Не рекомендуется: виден в истории команд")
    @click.option("--yes", is_flag=True)
    @click.option("--dry-run/--no-dry-run", default=True)
    def video_publish(video_id: str, passphrase: str | None, yes: bool, dry_run: bool) -> None:
        if dry_run or not yes:
            click.echo("dry-run / нужен --no-dry-run --yes")
            return
        passphrase = require_passphrase(passphrase)
        from aiyoutubehands.service_factory import build_youtube_service

        yt, client = build_youtube_service(passphrase=passphrase)
        try:
            yt.publish_video(video_id, dry_run=False, yes=True)
        finally:
            client.close()
        click.echo("video publish: OK")

    @video.command("schedule")
    @click.argument("video_id")
    @click.argument("publish_at")
    @click.option("--passphrase", default=None, help="Не рекомендуется: виден в истории команд")
    @click.option("--yes", is_flag=True)
    @click.option("--dry-run/--no-dry-run", default=True)
    def video_schedule(
        video_id: str,
        publish_at: str,
        passphrase: str | None,
        yes: bool,
        dry_run: bool,
    ) -> None:
        """publish_at: ISO8601, например 2026-10-01T15:00:00Z"""
        if dry_run or not yes:
            click.echo("dry-run / нужен --no-dry-run --yes")
            return
        passphrase = require_passphrase(passphrase)
        from aiyoutubehands.service_factory import build_youtube_service

        yt, client = build_youtube_service(passphrase=passphrase)
        try:
            yt.schedule_video(video_id, publish_at, dry_run=False, yes=True)
        finally:
            client.close()
        click.echo("video schedule: OK")

    @video.command("delete")
    @click.argument("video_id")
    @click.option("--passphrase", default=None, help="Не рекомендуется: виден в истории команд")
    @click.option("--yes", is_flag=True)
    @click.option("--dry-run/--no-dry-run", default=True)
    def video_delete(video_id: str, passphrase: str | None, yes: bool, dry_run: bool) -> None:
        if dry_run or not yes:
            click.echo("dry-run / нужен --no-dry-run --yes")
            return
        passphrase = require_passphrase(passphrase)
        from aiyoutubehands.service_factory import build_youtube_service

        yt, client = build_youtube_service(passphrase=passphrase)
        try:
            yt.delete_video(video_id, dry_run=False, yes=True)
        finally:
            client.close()
        click.echo("video delete: OK")

    @video.command("thumbnail")
    @click.argument("video_id")
    @click.argument("image_path", type=click.Path(exists=True))
    @click.option("--passphrase", default=None, help="Не рекомендуется: виден в истории команд")
    @click.option("--yes", is_flag=True)
    @click.option("--dry-run/--no-dry-run", default=True)
    def video_thumbnail(
        video_id: str,
        image_path: str,
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
            token = require_access_token(client.access_token)
            yt.set_thumbnail(
                video_id, image_path, access_token=token, dry_run=False, yes=True
            )
        finally:
            client.close()
        click.echo("video thumbnail: OK")
