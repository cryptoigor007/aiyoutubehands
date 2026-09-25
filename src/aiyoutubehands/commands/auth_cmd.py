"""auth commands."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click

from aiyoutubehands.config import get_config_dir, load_config_optional
from aiyoutubehands.token import TokenStore


def _token_path() -> Path:
    try:
        cfg = load_config_optional()
        return Path(cfg.auth.token_file)
    except Exception:
        return get_config_dir() / "token.age"


def _store_from_passphrase(passphrase: str, path: Path | None = None) -> TokenStore:
    return TokenStore(path=path or _token_path(), passphrase=passphrase)


def register(cli: click.Group) -> None:
    @cli.group()
    def auth() -> None:
        """Авторизация (OAuth2)."""

    @auth.command("status")
    @click.option("--passphrase", default=None, envvar="AYH_TOKEN_PASSPHRASE", help="Passphrase токена")
    @click.option("--json", "as_json", is_flag=True)
    def auth_status(passphrase: str | None, as_json: bool) -> None:
        """Статус токена."""
        path = _token_path()
        if not path.is_file():
            data = {"ok": False, "message": "Токен не настроен (выполните auth login)"}
            if as_json:
                click.echo(json.dumps(data, ensure_ascii=False))
            else:
                click.echo("auth: токен не настроен")
                click.echo("  Выполните: ayh auth login --stub --passphrase '...'")
            return

        if not passphrase:
            data = {
                "ok": False,
                "message": "Файл токена есть, укажите --passphrase или AYH_TOKEN_PASSPHRASE",
                "path": str(path),
            }
            if as_json:
                click.echo(json.dumps(data, ensure_ascii=False))
            else:
                click.echo(f"auth: файл есть ({path})")
                click.echo("  Укажите --passphrase для проверки health")
            return

        store = _store_from_passphrase(passphrase, path)
        health = store.health()
        if as_json:
            click.echo(json.dumps(health, ensure_ascii=False, indent=2))
        elif health.get("ok"):
            click.echo("auth: OK")
            click.echo(f"  expired: {health.get('expired')}")
            click.echo(f"  has_refresh: {health.get('has_refresh')}")
        else:
            click.echo(f"auth: ошибка [{health.get('error')}] {health.get('message')}")
            sys.exit(10)

    @auth.command("login")
    @click.option("--client-secrets", default=None, help="Путь к client_secrets.json")
    @click.option("--stub", is_flag=True, help="Использовать stub (без сети)")
    @click.option(
        "--passphrase",
        default=None,
        envvar="AYH_TOKEN_PASSPHRASE",
        help="Passphrase для шифрования токена",
    )
    @click.option("--yes", is_flag=True, help="Не спрашивать подтверждение перезаписи")
    def auth_login(
        client_secrets: str | None,
        stub: bool,
        passphrase: str | None,
        yes: bool,
    ) -> None:
        """OAuth login (Device Flow). Stub сохраняет токен при --passphrase."""
        from aiyoutubehands.auth_flow import device_flow_poll_stub, device_flow_start_stub

        if not stub and client_secrets is None:
            click.echo("Для реального login укажите --client-secrets и уберите --stub")
            click.echo("Сейчас доступен только --stub режим")
            stub = True

        if not stub:
            click.echo("Реальный OAuth flow ещё требует client_secrets + сеть")
            sys.exit(2)

        if not passphrase:
            click.echo("Укажите --passphrase (или AYH_TOKEN_PASSPHRASE) для сохранения токена")
            sys.exit(2)

        path = _token_path()
        if path.is_file() and not yes:
            click.echo(f"Файл уже существует: {path}")
            click.echo("Передайте --yes для перезаписи")
            sys.exit(2)

        dc = device_flow_start_stub("stub_client")
        click.echo(f"Откройте {dc.verification_url}")
        click.echo(f"Введите код: {dc.user_code}")
        token = device_flow_poll_stub(dc.device_code)
        store = _store_from_passphrase(passphrase, path)
        store.save(token)
        click.echo(f"Токен сохранён: {path}")
        click.echo("auth login: OK (stub)")

    @auth.command("logout")
    @click.option("--yes", is_flag=True, help="Подтвердить удаление")
    def auth_logout(yes: bool) -> None:
        """Удалить локальный файл токена и audit."""
        path = _token_path()
        audit = path.with_suffix(".audit.jsonl")
        if not path.is_file() and not audit.is_file():
            click.echo("auth logout: нечего удалять")
            return
        if not yes:
            click.echo(f"Будет удалён: {path}")
            click.echo("Передайте --yes для подтверждения")
            sys.exit(2)
        for p in (path, audit):
            if p.is_file():
                p.unlink()
                click.echo(f"Удалён: {p}")
        click.echo("auth logout: OK")
