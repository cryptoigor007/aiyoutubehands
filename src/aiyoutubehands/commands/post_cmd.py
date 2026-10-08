"""CLI: ayh post create — publish YouTube community posts (Safari automation)."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path

import click

from aiyoutubehands.posts.errors import PostsError
from aiyoutubehands.posts.models import PostPayload, PostValidationError
from aiyoutubehands.posts.safari import dry_run_plan, publish_post

CONFIRM_RE = re.compile(
    r"^\s*подтверждаю план от (\d{2})\.(\d{2})\.(\d{4}) #([0-9a-f]{6,})\s*$"
)


def _load_channel_id() -> str:
    """Load expected_channel_id from config (never log the full value)."""
    from aiyoutubehands.config import load_config

    cfg = load_config()
    if cfg.channel is None or not cfg.channel.expected_channel_id:
        raise PostValidationError(
            "expected_channel_id не задан в конфигурации",
            action="Укажите channel.expected_channel_id в config/local.yaml "
            "или ~/.config/aiyoutubehands/config.yaml",
        )
    return cfg.channel.expected_channel_id


def _plan_hash(payload: PostPayload, *, via: str) -> str:
    """Short stable hash of the plan for the confirmation phrase."""
    raw = f"{payload.channel_id}|{payload.text}|{payload.image or ''}|{payload.crop}|{via}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _check_confirm(confirm: str, plan_hash: str) -> None:
    """Validate the repo-standard confirmation phrase for a channel write."""
    m = CONFIRM_RE.match(confirm or "")
    if not m:
        raise click.ClickException(
            "Нужна точная фраза подтверждения: "
            "подтверждаю план от ДД.ММ.ГГГГ #<plan_hash>"
        )
    d, mo, y, h = m.groups()
    today = date.today()
    if (int(d), int(mo), int(y)) != (today.day, today.month, today.year):
        raise click.ClickException(
            "Дата во фразе не сегодняшняя — план нужно подтверждать в день запуска"
        )
    if h != plan_hash:
        raise click.ClickException(
            "Хеш во фразе не совпадает с планом (пересоберите dry-run)"
        )


def register(cli: click.Group) -> None:
    @cli.group()
    def post() -> None:
        """Записи (community posts) на канал."""

    @post.command("create")
    @click.option(
        "--text-file",
        "text_file",
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
        required=True,
        help="Файл с текстом записи (UTF-8)",
    )
    @click.option(
        "--image",
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
        default=None,
        help="Опциональная картинка (jpg/png/gif/webp)",
    )
    @click.option(
        "--crop",
        type=click.Choice(["center", "left", "right", "top", "bottom"]),
        default="center",
        show_default=True,
        help="Кадрирование картинки под квадрат в ленте",
    )
    @click.option(
        "--via",
        type=click.Choice(["api", "ui"]),
        default="api",
        show_default=True,
        help="api — веб-API из страницы (рекомендуется); ui — DOM (только текст)",
    )
    @click.option(
        "--dry-run/--no-dry-run",
        default=True,
        show_default=True,
        help="Показать план без публикации (по умолчанию включено)",
    )
    @click.option(
        "--yes",
        is_flag=True,
        default=False,
        help="Подтвердить публикацию (вместе с --no-dry-run и --confirm)",
    )
    @click.option(
        "--confirm",
        "confirm",
        default="",
        help="Фраза подтверждения: «подтверждаю план от ДД.ММ.ГГГГ #<plan_hash>»",
    )
    @click.option("--json", "as_json", is_flag=True, help="Вывод в JSON")
    def post_create(
        text_file: Path,
        image: Path | None,
        crop: str,
        via: str,
        dry_run: bool,
        yes: bool,
        confirm: str,
        as_json: bool,
    ) -> None:
        """Создать «Запись» (community post) на канале через Safari.

        Официальный API не поддерживает создание записей — используется
        веб-автоматизация Safari (только macOS).

        Безопасность: по умолчанию --dry-run. Реальная публикация требует
        --no-dry-run, --yes и точной фразы --confirm по правилам репозитория.
        """
        try:
            channel_id = _load_channel_id()
            payload = PostPayload.from_files(
                text_file, image, channel_id=channel_id, crop=crop
            )
        except PostValidationError as exc:
            raise click.ClickException(f"{exc.message} — {exc.action}") from exc
        except Exception as exc:
            msg = getattr(exc, "message", None) or str(exc)
            action = getattr(exc, "action", "") or ""
            raise click.ClickException(
                f"{msg}" + (f" — {action}" if action else "")
            ) from exc

        plan = dry_run_plan(payload, via=via)
        plan_hash = _plan_hash(payload, via=via)
        plan["plan_hash"] = plan_hash
        plan["confirm_phrase"] = (
            f"подтверждаю план от {date.today().strftime('%d.%m.%Y')} #{plan_hash}"
        )

        if dry_run:
            if as_json:
                click.echo(json.dumps(plan, ensure_ascii=False, indent=2))
            else:
                click.echo("=== DRY-RUN: план публикации «Записи» ===")
                click.echo(f"URL:          {plan.get('url')}")
                click.echo(f"Путь:         {plan['via']}")
                click.echo(f"Текст ({plan['text_len']} симв.): {plan['text_preview']}")
                click.echo(f"Картинка:     {plan.get('image') or '(нет)'}")
                if plan.get("image"):
                    click.echo(f"Размер:       {plan.get('image_size') or 'не распознан'}")
                    coords = plan.get("preview_coordinates")
                    click.echo(f"Кадр:         {plan.get('crop')} → {coords}")
                if plan.get("image_requirements"):
                    click.echo()
                    click.echo(plan["image_requirements"])
                click.echo(
                    f"Платформа:    {plan['platform']} "
                    f"(Safari available: {plan['safari_available']})"
                )
                click.echo("Шаги:")
                for s in plan["steps"]:
                    click.echo(f"  {s}")
                click.echo()
                click.echo("Для реальной публикации на macOS выполните:")
                click.echo(
                    f"  ayh post create --text-file {text_file} "
                    f"{'--image ' + str(image) + ' ' if image else ''}"
                    f"{'--crop ' + crop + ' ' if image else ''}"
                    f"{'--via ' + via + ' ' if via != 'api' else ''}"
                    "--no-dry-run --yes --confirm "
                    f"\"{plan['confirm_phrase']}\""
                )
            return

        if not yes:
            raise click.ClickException(
                "Для публикации нужен флаг --yes (и фраза --confirm). "
                "Сначала посмотрите dry-run."
            )
        _check_confirm(confirm, plan_hash)

        if not plan["safari_available"]:
            raise click.ClickException(
                "Safari automation доступна только на macOS. "
                "Запустите команду на Mac."
            )

        click.echo(f"Публикация «Записи» (путь: {via}) через Safari…")
        try:
            result = publish_post(
                payload, via=via, progress=lambda msg: click.echo(f"  {msg}")
            )
        except PostsError as exc:
            raise click.ClickException(f"{exc.message} — {exc.action}") from exc

        if as_json:
            click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            click.echo("OK: публикация выполнена.")
            if result.get("verified"):
                click.echo("Проверка: запись найдена на /posts ✔")
            else:
                click.echo(
                    "Проверка: автоматически найти не удалось — "
                    f"откройте https://www.youtube.com/channel/{channel_id}/posts "
                    "и убедитесь вручную."
                )
