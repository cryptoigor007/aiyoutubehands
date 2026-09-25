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

    @ai.command("chapters")
    @click.argument("topic")
    def ai_chapters(topic: str) -> None:
        """Главы / таймкоды."""
        from aiyoutubehands.ai import AIEngine

        click.echo(AIEngine().generate_chapters(topic))

    @ai.command("translate")
    @click.argument("text")
    @click.option("--lang", default="en")
    def ai_translate(text: str, lang: str) -> None:
        """Перевод текста."""
        from aiyoutubehands.ai import AIEngine

        click.echo(AIEngine().translate(text, lang=lang))

    @ai.command("calendar")
    @click.argument("niche")
    @click.option("--days", default=7, type=int)
    def ai_calendar(niche: str, days: int) -> None:
        """Контент-календарь."""
        from aiyoutubehands.ai import AIEngine

        click.echo(AIEngine().content_calendar(niche, days=days))
