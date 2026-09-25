"""CLI entry point for AI YouTube Hands."""

from __future__ import annotations

import click

from aiyoutubehands import __version__
from aiyoutubehands.commands import register_all
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


register_all(cli)


if __name__ == "__main__":
    cli()
