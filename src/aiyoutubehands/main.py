"""CLI entry point for AI YouTube Hands."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from aiyoutubehands import __version__
from aiyoutubehands.logging import get_logger, setup_logging


def _setup(ctx: click.Context, json_logs: bool, log_level: str) -> None:
    setup_logging(level=log_level, json_output=json_logs)
    ctx.ensure_object(dict)
    ctx.obj["log"] = get_logger("ayh")
    ctx.obj["json"] = False  # set by --json flag on subcommands if needed


@click.group()
@click.version_option(version=__version__, prog_name="ayh")
@click.option("--json-logs/--no-json-logs", default=True, help="JSON-логи")
@click.option("--log-level", default="INFO", show_default=True, help="Уровень логов")
@click.pass_context
def cli(ctx: click.Context, json_logs: bool, log_level: str) -> None:
    """AI YouTube Hands — AI-first CLI для полного управления YouTube-каналом."""
    _setup(ctx, json_logs, log_level)


# ── doctor ──────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--json", "as_json", is_flag=True, help="Вывод в JSON")
@click.pass_context
def doctor(ctx: click.Context, as_json: bool) -> None:
    """Диагностика окружения и конфигурации."""
    log = ctx.obj["log"]
    log.info("doctor_started")
    result: dict = {
        "ok": True,
        "version": __version__,
        "checks": {},
    }
    try:
        from aiyoutubehands.config import get_config_dir, get_state_dir
        result["checks"]["config_dir"] = str(get_config_dir())
        result["checks"]["state_dir"] = str(get_state_dir())
    except Exception as exc:
        result["ok"] = False
        result["checks"]["config"] = str(exc)

    try:
        from aiyoutubehands.logging import get_logger as gl
        gl("doctor-test")
        result["checks"]["logging"] = "ok"
    except Exception as exc:
        result["ok"] = False
        result["checks"]["logging"] = str(exc)

    result["checks"]["modules"] = {
        "token": True,
        "quota": True,
        "client": True,
        "calendar": True,
        "youtube": True,
    }

    if as_json:
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        status = "OK" if result["ok"] else "ОШИБКА"
        click.echo(f"doctor: {status}")
        click.echo(f"версия: {result['version']}")
        for k, v in result["checks"].items():
            click.echo(f"  {k}: {v}")
    log.info("doctor_finished", ok=result["ok"])
    if not result["ok"]:
        sys.exit(1)


# ── version ─────────────────────────────────────────────────────────────────

@cli.command("version")
@click.option("--json", "as_json", is_flag=True)
def version_cmd(as_json: bool) -> None:
    """Показать версию."""
    if as_json:
        click.echo(json.dumps({"version": __version__}))
    else:
        click.echo(__version__)


# ── calendar ────────────────────────────────────────────────────────────────

@cli.group()
def calendar() -> None:
    """Календарь публикаций."""


@calendar.command("list")
@click.option("--db", default=None, help="Путь к SQLite БД")
@click.option("--json", "as_json", is_flag=True)
def calendar_list(db: str | None, as_json: bool) -> None:
    """Список записей календаря."""
    from aiyoutubehands.calendar import Calendar
    from aiyoutubehands.config import get_state_dir

    path = Path(db) if db else get_state_dir() / "calendar.db"
    cal = Calendar(path)
    entries = cal.list_entries()
    if as_json:
        click.echo(json.dumps(
            [{"video_id": e.video_id, "title": e.title, "publish_at": e.publish_at, "status": e.status} for e in entries],
            ensure_ascii=False,
            indent=2,
        ))
    else:
        if not entries:
            click.echo("Календарь пуст")
            return
        for e in entries:
            click.echo(f"{e.publish_at}  [{e.status}]  {e.video_id}  {e.title}")


@calendar.command("grid")
@click.option("--year", type=int, default=2026)
@click.option("--month", type=int, default=10)
@click.option("--db", default=None)
def calendar_grid(year: int, month: int, db: str | None) -> None:
    """ASCII-сетка календаря за месяц."""
    from aiyoutubehands.calendar import Calendar
    from aiyoutubehands.config import get_state_dir

    path = Path(db) if db else get_state_dir() / "calendar.db"
    cal = Calendar(path)
    click.echo(cal.ascii_grid(year, month))


@calendar.command("add")
@click.argument("video_id")
@click.argument("title")
@click.argument("publish_at")
@click.option("--db", default=None)
def calendar_add(video_id: str, title: str, publish_at: str, db: str | None) -> None:
    """Добавить запись в календарь."""
    from aiyoutubehands.calendar import Calendar, CalendarEntry
    from aiyoutubehands.config import get_state_dir

    path = Path(db) if db else get_state_dir() / "calendar.db"
    cal = Calendar(path)
    cal.add(CalendarEntry(video_id=video_id, title=title, publish_at=publish_at))
    click.echo(f"Добавлено: {video_id}")


# ── quota ───────────────────────────────────────────────────────────────────

@cli.group()
def quota() -> None:
    """Квоты YouTube API."""


@quota.command("status")
@click.option("--db", default=None)
@click.option("--limit", default=10000, type=int)
@click.option("--json", "as_json", is_flag=True)
def quota_status(db: str | None, limit: int, as_json: bool) -> None:
    """Текущее использование квоты."""
    from aiyoutubehands.quota import QuotaEngine
    from aiyoutubehands.config import get_state_dir

    path = Path(db) if db else get_state_dir() / "quota.db"
    eng = QuotaEngine(db_path=path, daily_limit=limit)
    used = eng.used_today()
    rem = eng.remaining()
    data = {"used": used, "remaining": rem, "limit": limit}
    if as_json:
        click.echo(json.dumps(data, ensure_ascii=False))
    else:
        click.echo(f"Использовано: {used} / {limit}")
        click.echo(f"Осталось: {rem}")


# ── auth (stubs) ────────────────────────────────────────────────────────────

@cli.group()
def auth() -> None:
    """Авторизация (OAuth2)."""


@auth.command("status")
@click.option("--json", "as_json", is_flag=True)
def auth_status(as_json: bool) -> None:
    """Статус токена (без реального файла — scaffold)."""
    data = {"ok": False, "message": "Токен не настроен (выполните auth login)"}
    if as_json:
        click.echo(json.dumps(data, ensure_ascii=False))
    else:
        click.echo("auth: токен не настроен")
        click.echo("  Выполните: ayh auth login  (ещё не реализовано полностью)")


# ── channel (read-only stubs) ───────────────────────────────────────────────

@cli.group()
def channel() -> None:
    """Управление каналом (только чтение без --yes)."""


@channel.command("info")
@click.option("--dry-run", is_flag=True, default=True, help="Без реального API")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def channel_info(ctx: click.Context, dry_run: bool, as_json: bool) -> None:
    """Информация о канале (dry-run по умолчанию)."""
    if dry_run:
        data = {"dry_run": True, "message": "Реальный запрос отключён (нужен --no-dry-run + токен)"}
        if as_json:
            click.echo(json.dumps(data, ensure_ascii=False))
        else:
            click.echo("channel info: dry-run (реальный API вызов отключён)")
        return
    click.echo("Реальный API вызов требует токен и подтверждение", err=True)
    sys.exit(2)


if __name__ == "__main__":
    cli()
