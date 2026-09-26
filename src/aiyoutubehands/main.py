"""CLI entry point for AI YouTube Hands."""

from __future__ import annotations

import sys

import click

from aiyoutubehands import __version__
from aiyoutubehands.cli_errors import handle_cli_error
from aiyoutubehands.commands import register_all
from aiyoutubehands.exceptions import EXIT_OK
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


def main(argv: list[str] | None = None) -> int:
    """Run CLI and map domain errors to exit codes."""
    try:
        cli.main(args=argv, prog_name="ayh", standalone_mode=False)
        return EXIT_OK
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return EXIT_OK
        if isinstance(code, int):
            return code
        return EXIT_OK if not code else 1
    except BaseException as exc:
        return handle_cli_error(exc)


if __name__ == "__main__":
    sys.exit(main())
