"""CLI command registration."""

from __future__ import annotations

from typing import Any

import click


def register_all(cli: click.Group) -> None:
    """Attach all subcommands to the root group."""
    from aiyoutubehands.commands import (
        ai_cmd,
        auth_cmd,
        calendar_cmd,
        channel_cmd,
        doctor_cmd,
        quota_cmd,
        upload_cmd,
        video_cmd,
    )

    doctor_cmd.register(cli)
    calendar_cmd.register(cli)
    quota_cmd.register(cli)
    auth_cmd.register(cli)
    channel_cmd.register(cli)
    video_cmd.register(cli)
    upload_cmd.register(cli)
    ai_cmd.register(cli)

    @cli.command("version")
    @click.option("--json", "as_json", is_flag=True)
    def version_cmd(as_json: bool) -> None:
        """Показать версию."""
        import json as json_lib

        from aiyoutubehands import __version__

        if as_json:
            click.echo(json_lib.dumps({"version": __version__}))
        else:
            click.echo(__version__)
