"""CLI entry point for AI YouTube Hands."""

from __future__ import annotations

import click

from aiyoutubehands import __version__
from aiyoutubehands.logging import get_logger, setup_logging


@click.group()
@click.version_option(version=__version__, prog_name="ayh")
@click.option("--json-logs/--no-json-logs", default=True, help="JSON-логи")
@click.option("--log-level", default="INFO", show_default=True, help="Уровень логов")
@click.pass_context
def cli(ctx: click.Context, json_logs: bool, log_level: str) -> None:
    """AI YouTube Hands — AI-first CLI для полного управления YouTube-каналом."""
    setup_logging(level=log_level, json_output=json_logs)
    ctx.ensure_object(dict)
    ctx.obj["log"] = get_logger("ayh")


@cli.command()
@click.pass_context
def doctor(ctx: click.Context) -> None:
    """Диагностика окружения и конфигурации."""
    log = ctx.obj["log"]
    log.info("doctor_started")
    click.echo("doctor: шаг 2 — logging и config готовы")
    click.echo(f"версия: {__version__}")
    try:
        from aiyoutubehands.config import get_config_dir, get_state_dir
        click.echo(f"config_dir: {get_config_dir()}")
        click.echo(f"state_dir: {get_state_dir()}")
    except Exception as exc:
        click.echo(f"ошибка конфигурации: {exc}")
    log.info("doctor_finished")


if __name__ == "__main__":
    cli()
