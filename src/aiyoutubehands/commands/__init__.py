"""CLI command registration."""

from __future__ import annotations

import click


def register_all(cli: click.Group) -> None:
    """Attach all subcommands to the root group."""
    from aiyoutubehands.commands import (
        ai_cmd,
        auth_cmd,
        calendar_cmd,
        captions_cmd,
        channel_cmd,
        comments_cmd,
        connect_cmd,
        doctor_cmd,
        playlist_cmd,
        quota_cmd,
        setup_cmd,
        upload_cmd,
        video_cmd,
    )

    doctor_cmd.register(cli)
    calendar_cmd.register(cli)
    quota_cmd.register(cli)
    setup_cmd.register(cli)
    connect_cmd.register(cli)
    auth_cmd.register(cli)
    channel_cmd.register(cli)
    video_cmd.register(cli)
    upload_cmd.register(cli)
    comments_cmd.register(cli)
    captions_cmd.register(cli)
    playlist_cmd.register(cli)
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
