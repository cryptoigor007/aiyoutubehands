"""auth commands."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click

from aiyoutubehands.config import get_config_dir, load_config_optional
from aiyoutubehands.token import EncryptedJsonStore, TokenStore


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
        return get_config_dir() / "client_secrets.age"


def _local_passphrase(passphrase: str | None, *, confirm: bool = False) -> str:
    """Prompt locally so the passphrase never enters shell history or logs.

    AYH_PASSPHRASE — неинтерактивный путь для агентов и скриптов; приглашение
    пишется в stderr, чтобы не ломать --json.
    """
    if passphrase:
        return passphrase
    env = os.environ.get("AYH_PASSPHRASE")
    if env:
        return env
    return str(
        click.prompt(
            "Пароль локального хранилища",
            hide_input=True,
            confirmation_prompt=confirm,
            err=True,
        )
    )


def register(cli: click.Group) -> None:
    @cli.group()
    def auth() -> None:
        """Авторизация OAuth2 через системный браузер."""

    @auth.command("status")
    @click.option("--json", "as_json", is_flag=True)
    def auth_status(as_json: bool) -> None:
        """Статус токена."""
        path = _token_path()
        if not path.is_file():
            data = {"ok": False, "message": "Токен не настроен"}
            click.echo(
                json.dumps(data, ensure_ascii=False) if as_json else "auth: токен не настроен"
            )
            return
        passphrase = _local_passphrase(None)
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
    @click.option("--stub", is_flag=True, help="Офлайн stub без Google")
    @click.option("--yes", is_flag=True)
    def auth_login(
        stub: bool,
        yes: bool,
    ) -> None:
        """Browser-based OAuth login from an encrypted local OAuth vault."""
        from aiyoutubehands.auth_flow import (
            desktop_flow_authorize,
            device_flow_poll_stub,
            device_flow_start_stub,
            load_client_secrets,
        )

        path = _token_path()
        if path.is_file() and not yes:
            click.echo(f"Токен уже есть: {path}. Передайте --yes для перезаписи")
            sys.exit(2)

        passphrase = _local_passphrase(None)

        if stub:
            dc = device_flow_start_stub("stub")
            click.echo(f"Откройте {dc.verification_url}")
            click.echo(f"Код: {dc.user_code}")
            token = device_flow_poll_stub(dc.device_code)
        else:
            secrets = load_client_secrets(_secrets_path(), passphrase=passphrase)
            client_id = str(secrets["client_id"])
            client_secret = str(secrets.get("client_secret") or "")
            if not client_secret:
                click.echo("В client_secrets нет client_secret")
                sys.exit(2)
            click.echo(
                "Откроется системный браузер. Войдите в нужный аккаунт и подтвердите доступ."
            )
            token = desktop_flow_authorize(client_id, client_secret)

        TokenStore(path=path, passphrase=passphrase).save(token)
        click.echo(f"Токен сохранён: {path}")
        click.echo("auth login: OK")

    @auth.command("import-client-secrets")
    @click.option(
        "--source", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path)
    )
    @click.option("--yes", is_flag=True, help="Разрешить замену существующего хранилища")
    def import_client_secrets(source: Path, yes: bool) -> None:
        """Encrypt a downloaded Google OAuth client JSON into the local vault."""
        from aiyoutubehands.auth_flow import read_client_secrets_json

        path = _secrets_path()
        if path.is_file() and not yes:
            click.echo(
                f"Зашифрованный OAuth-клиент уже есть: {path}. Передайте --yes для перезаписи"
            )
            sys.exit(2)
        passphrase = _local_passphrase(None, confirm=True)
        secrets = read_client_secrets_json(source)
        EncryptedJsonStore(path, passphrase=passphrase).save(secrets)
        click.echo(f"OAuth-клиент зашифрован: {path}")
        click.echo("Исходный JSON не удалён автоматически. Удалите его после проверки.")

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
