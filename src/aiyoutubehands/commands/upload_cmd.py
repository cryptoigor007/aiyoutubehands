"""upload commands."""

from __future__ import annotations

import json

import click

from aiyoutubehands.client import require_access_token
from aiyoutubehands.commands.security import require_passphrase


def register(cli: click.Group) -> None:
    @cli.group()
    def upload() -> None:
        """Загрузка видео (resumable)."""

    @upload.command("prepare")
    @click.argument("file_path", type=click.Path(exists=True))
    @click.option("--title", required=True)
    @click.option("--description", default="")
    @click.option(
        "--privacy", default="private", type=click.Choice(["private", "unlisted", "public"])
    )
    @click.option(
        "--notify-subscribers/--no-notify-subscribers",
        default=True,
        help="Уведомлять подписчиков при публикации",
    )
    @click.option("--json", "as_json", is_flag=True)
    def upload_prepare(
        file_path: str,
        title: str,
        description: str,
        privacy: str,
        notify_subscribers: bool,
        as_json: bool,
    ) -> None:
        """План загрузки без отправки."""
        from aiyoutubehands.upload import execute_upload_dry_run, prepare_upload

        plan = prepare_upload(
            file_path,
            title=title,
            description=description,
            privacy=privacy,
            notify_subscribers=notify_subscribers,
        )
        result = execute_upload_dry_run(plan)
        if as_json:
            click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            click.echo("План (dry-run):")
            click.echo(f"  файл: {plan.file_path} ({plan.size} байт)")
            click.echo(f"  title: {plan.snippet.title}")
            click.echo(f"  privacy: {plan.status.privacy_status}")
            click.echo(f"  уведомлять подписчиков: {'да' if plan.notify_subscribers else 'нет'}")

    @upload.command("run")
    @click.argument("file_path", type=click.Path(exists=True))
    @click.option("--title", required=True)
    @click.option("--description", default="")
    @click.option(
        "--privacy", default="private", type=click.Choice(["private", "unlisted", "public"])
    )
    @click.option(
        "--notify-subscribers/--no-notify-subscribers",
        default=True,
        help="Уведомлять подписчиков при публикации",
    )
    @click.option("--yes", is_flag=True, help="Реальная загрузка")
    @click.option("--dry-run/--no-dry-run", default=True)
    @click.option("--json", "as_json", is_flag=True)
    def upload_run(
        file_path: str,
        title: str,
        description: str,
        privacy: str,
        notify_subscribers: bool,
        yes: bool,
        dry_run: bool,
        as_json: bool,
    ) -> None:
        """Resumable upload. По умолчанию dry-run; для сети: --no-dry-run --yes."""
        from aiyoutubehands.upload import (
            execute_resumable_upload,
            execute_upload_dry_run,
            prepare_upload,
        )

        plan = prepare_upload(
            file_path,
            title=title,
            description=description,
            privacy=privacy,
            dry_run=dry_run,
            notify_subscribers=notify_subscribers,
        )
        if dry_run or not yes:
            result = execute_upload_dry_run(plan)
            if not yes and not dry_run:
                result["message"] = "Нужны --no-dry-run и --yes для реальной загрузки"
            if as_json:
                click.echo(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                click.echo(result.get("message", "dry-run"))
            return

        passphrase = require_passphrase(None)

        from aiyoutubehands.service_factory import build_youtube_service

        yt, client = build_youtube_service(passphrase=passphrase)
        try:
            token = require_access_token(client.access_token)
            result = execute_resumable_upload(
                plan,
                token,
                quota=yt.quota,
                yes=True,
            )
        finally:
            client.close()

        if as_json:
            # strip huge raw if needed
            out = {k: v for k, v in result.items() if k != "raw"}
            click.echo(json.dumps(out, ensure_ascii=False, indent=2))
        else:
            click.echo(f"upload OK video_id={result.get('video_id')}")
