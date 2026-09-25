"""upload commands."""

from __future__ import annotations

import json

import click


def register(cli: click.Group) -> None:
    @cli.group()
    def upload() -> None:
        """Загрузка видео (только prepare / dry-run)."""

    @upload.command("prepare")
    @click.argument("file_path", type=click.Path(exists=True))
    @click.option("--title", required=True)
    @click.option("--description", default="")
    @click.option(
        "--privacy",
        default="private",
        type=click.Choice(["private", "unlisted", "public"]),
    )
    @click.option("--json", "as_json", is_flag=True)
    def upload_prepare(
        file_path: str,
        title: str,
        description: str,
        privacy: str,
        as_json: bool,
    ) -> None:
        """Подготовить план загрузки (без реальной отправки)."""
        from aiyoutubehands.upload import execute_upload_dry_run, prepare_upload

        plan = prepare_upload(
            file_path,
            title=title,
            description=description,
            privacy=privacy,
            dry_run=True,
        )
        result = execute_upload_dry_run(plan)
        if as_json:
            click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            click.echo("План загрузки (dry-run):")
            click.echo(f"  файл: {plan.file_path}")
            click.echo(f"  размер: {plan.size} байт")
            click.echo(f"  sha256: {plan.sha256[:16]}...")
            click.echo(f"  title: {plan.snippet.title}")
            click.echo(f"  privacy: {plan.status.privacy_status}")
            click.echo("Реальная загрузка не выполнена.")
