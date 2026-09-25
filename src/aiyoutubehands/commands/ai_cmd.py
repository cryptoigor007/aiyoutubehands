"""ai commands."""

from __future__ import annotations

import click


def register(cli: click.Group) -> None:
    @cli.group()
    def ai() -> None:
        """AI-команды (локальный провайдер по умолчанию)."""

    @ai.command("title")
    @click.argument("topic")
    def ai_title(topic: str) -> None:
        """Сгенерировать заголовок."""
        from aiyoutubehands.ai import AIEngine

        click.echo(AIEngine().generate_title(topic))

    @ai.command("description")
    @click.argument("topic")
    def ai_description(topic: str) -> None:
        """Сгенерировать описание."""
        from aiyoutubehands.ai import AIEngine

        click.echo(AIEngine().generate_description(topic))

    @ai.command("tags")
    @click.argument("topic")
    def ai_tags(topic: str) -> None:
        """Сгенерировать теги."""
        from aiyoutubehands.ai import AIEngine

        click.echo(", ".join(AIEngine().generate_tags(topic)))

    @ai.command("script")
    @click.argument("topic")
    def ai_script(topic: str) -> None:
        """Сгенерировать сценарий."""
        from aiyoutubehands.ai import AIEngine

        click.echo(AIEngine().generate_script(topic))

    @ai.command("thumbnail")
    @click.argument("topic")
    def ai_thumbnail(topic: str) -> None:
        """Промпт для обложки."""
        from aiyoutubehands.ai import AIEngine

        click.echo(AIEngine().generate_thumbnail_prompt(topic))
