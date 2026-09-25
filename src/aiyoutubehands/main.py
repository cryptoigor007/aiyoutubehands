"""CLI entry point for AI YouTube Hands."""

from __future__ import annotations

import click

from aiyoutubehands import __version__


@click.group()
@click.version_option(version=__version__, prog_name="ayh")
def cli() -> None:
    """AI YouTube Hands  AI-first CLI for full YouTube channel control."""


@cli.command()
def doctor() -> None:
    """Run diagnostic checks."""
    click.echo("doctor: scaffold only  not implemented yet")


if __name__ == "__main__":
    cli()
