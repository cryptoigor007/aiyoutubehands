"""auth commands."""

from __future__ import annotations

import json
import sys

import click


def register(cli: click.Group) -> None:
    @cli.group()
    def auth() -> None:
        """Авторизация (OAuth2)."""

    @auth.command("status")
    @click.option("--json", "as_json", is_flag=True)
    def auth_status(as_json: bool) -> None:
        """Статус токена."""
        data = {"ok": False, "message": "Токен не настроен (выполните auth login)"}
        if as_json:
            click.echo(json.dumps(data, ensure_ascii=False))
        else:
            click.echo("auth: токен не настроен")
            click.echo("  Выполните: ayh auth login --stub")

    @auth.command("login")
    @click.option("--client-secrets", default=None, help="Путь к client_secrets.json")
    @click.option("--stub", is_flag=True, help="Использовать stub (без сети)")
    def auth_login(client_secrets: str | None, stub: bool) -> None:
        """OAuth login (Device Flow). По умолчанию — stub."""
        from aiyoutubehands.auth_flow import device_flow_poll_stub, device_flow_start_stub

        if not stub and client_secrets is None:
            click.echo("Для реального login укажите --client-secrets и уберите --stub")
            click.echo("Сейчас доступен только --stub режим")
            stub = True

        if stub:
            dc = device_flow_start_stub("stub_client")
            click.echo(f"Откройте {dc.verification_url}")
            click.echo(f"Введите код: {dc.user_code}")
            token = device_flow_poll_stub(dc.device_code)
            click.echo("stub: токен сгенерирован в памяти (не сохранён постоянно без ключа)")
            click.echo(f"access_token: {token.access_token[:12]}...")
            click.echo("Для постоянного хранения нужен ключ шифрования (passphrase).")
            return

        click.echo("Реальный OAuth flow ещё требует настройки client_secrets + ключ")
        sys.exit(2)
