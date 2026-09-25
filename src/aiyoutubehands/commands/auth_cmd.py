"""auth commands."""

from __future__ import annotations

import json
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


def _secrets_path() -> Path:
    try:
        cfg = load_config_optional()
        return Path(cfg.auth.client_secrets_file)
    except Exception:
        return get_config_dir() / "client_secrets.json"


def register(cli: click.Group) -> None:
    @cli.group()
    def auth() -> None:
        """Авторизация (OAuth2 Device Flow)."""

    @auth.command("status")
    @click.option("--passphrase", default=None, envvar="AYH_TOKEN_PASSPHRASE")
    @click.option("--json", "as_json", is_flag=True)
    def auth_status(passphrase: str | None, as_json: bool) -> None:
        """Статус токена."""
        path = _token_path()
        if not path.is_file():
            data = {"ok": False, "message": "Токен не настроен"}
            click.echo(json.dumps(data, ensure_ascii=False) if as_json else "auth: токен не настроен")
            return
        if not passphrase:
            msg = f"Файл есть ({path}), укажите --passphrase"
            click.echo(json.dumps({"ok": False, "path": str(path), "message": msg}, ensure_ascii=False) if as_json else f"auth: {msg}")
            return
        health = TokenStore(path=path, passphrase=passphrase).health()
        if as_json:
            click.echo(json.dumps(health, ensure_ascii=False, indent=2))
        elif health.get("ok"):
            click.echo("auth: OK")
            click.echo(f"  expired: {health.get('expired')}")
        else:
            click.echo(f"auth: ошибка [{health.get('error')}]")
            sys.exit(10)

    @auth.command("login")
    @click.option("--client-secrets", default=None, type=click.Path())
    @click.option("--stub", is_flag=True, help="Офлайн stub без Google")
    @click.option("--passphrase", default=None, envvar="AYH_TOKEN_PASSPHRASE")
    @click.option("--yes", is_flag=True)
    def auth_login(
        client_secrets: str | None,
        stub: bool,
        passphrase: str | None,
        yes: bool,
    ) -> None:
        """Device Flow login. Без --stub нужен client_secrets.json."""
        from aiyoutubehands.auth_flow import (
            device_flow_poll,
            device_flow_poll_stub,
            device_flow_start,
            device_flow_start_stub,
            load_client_secrets,
        )

        if not passphrase:
            click.echo("Нужен --passphrase (или AYH_TOKEN_PASSPHRASE)")
            sys.exit(2)

        path = _token_path()
        if path.is_file() and not yes:
            click.echo(f"Токен уже есть: {path}. Передайте --yes для перезаписи")
            sys.exit(2)

        if stub:
            dc = device_flow_start_stub("stub")
            click.echo(f"Откройте {dc.verification_url}")
            click.echo(f"Код: {dc.user_code}")
            token = device_flow_poll_stub(dc.device_code)
        else:
            secrets_path = Path(client_secrets) if client_secrets else _secrets_path()
            secrets = load_client_secrets(secrets_path)
            client_id = str(secrets["client_id"])
            client_secret = str(secrets.get("client_secret") or "")
            if not client_secret:
                click.echo("В client_secrets нет client_secret")
                sys.exit(2)
            dc = device_flow_start(client_id)
            click.echo(f"Откройте: {dc.verification_url}")
            click.echo(f"Введите код: {dc.user_code}")
            click.echo("Ожидание подтверждения в браузере...")
            token = device_flow_poll(
                client_id,
                client_secret,
                dc.device_code,
                interval=dc.interval,
                expires_in=dc.expires_in,
            )

        TokenStore(path=path, passphrase=passphrase).save(token)
        click.echo(f"Токен сохранён: {path}")
        click.echo("auth login: OK")

    @auth.command("logout")
    @click.option("--yes", is_flag=True)
    def auth_logout(yes: bool) -> None:
        path = _token_path()
        audit = path.with_suffix(".audit.jsonl")
        if not path.is_file() and not audit.is_file():
            click.echo("auth logout: нечего удалять")
            return
        if not yes:
            click.echo("Передайте --yes")
            sys.exit(2)
        for p in (path, audit):
            if p.is_file():
                p.unlink()
                click.echo(f"Удалён: {p}")
        click.echo("auth logout: OK")
