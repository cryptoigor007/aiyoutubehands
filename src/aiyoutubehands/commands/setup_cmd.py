"""Interactive-free onboarding guidance for the YouTube integration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from aiyoutubehands.auth_flow import SCOPES
from aiyoutubehands.config import get_config_dir, load_config_optional


def _local_status() -> dict[str, Any]:
    config_dir = get_config_dir()
    cfg = load_config_optional()
    oauth_vault = Path(cfg.auth.client_secrets_file)
    token_vault = Path(cfg.auth.token_file)
    return {
        "config_file": str(config_dir / "config.yaml"),
        "oauth_vault": str(oauth_vault),
        "oauth_vault_exists": oauth_vault.is_file(),
        "token_vault": str(token_vault),
        "token_vault_exists": token_vault.is_file(),
        "channel_id": cfg.channel.expected_channel_id if cfg.channel else None,
    }


def register(cli: click.Group) -> None:
    @cli.command("setup")
    @click.option("--json", "as_json", is_flag=True, help="Вывести состояние в JSON")
    def setup(as_json: bool) -> None:
        """Show current YouTube API setup instructions and local progress."""
        status = _local_status()
        if as_json:
            click.echo(
                json.dumps({"status": status, "scopes": SCOPES}, ensure_ascii=False, indent=2)
            )
            return

        click.echo("YouTube API: настройка приложения")
        click.echo("")
        click.echo("Google Cloud")
        click.echo("1. Откройте https://console.cloud.google.com/ и создайте либо выберите проект.")
        click.echo("2. APIs & Services -> Library -> включите YouTube Data API v3.")
        click.echo("3. Google Auth Platform -> Branding/Audience: заполните экран согласия OAuth.")
        click.echo("4. Если приложение в Testing, добавьте свой Google-аккаунт в Test users.")
        click.echo("5. Credentials -> Create credentials -> OAuth client ID -> Desktop app.")
        click.echo(
            "6. Скачайте JSON OAuth-клиента. Не используйте API key и не выбирайте TV client."
        )
        click.echo("")
        click.echo("Локально")
        click.echo(
            "7. Найдите ID канала (начинается с UC) в YouTube Settings -> Advanced settings."
        )
        click.echo("8. Подключите всё одной командой:")
        click.echo('   ayh connect --channel-id "UC..."')
        click.echo("   Команда сама шифрует данные, создаёт конфиг, удаляет исходный JSON")
        click.echo("   и открывает браузер для выбора Google-аккаунта.")
        click.echo("9. Проверьте: ayh auth status && ayh channel info --no-dry-run")
        click.echo("")
        click.echo("Безопасность")
        click.echo("- OAuth-клиент и токен хранятся только в зашифрованных файлах с правами 600.")
        click.echo(
            "- Пароль вводится скрыто и не сохраняется в истории команд или переменных окружения."
        )
        click.echo(
            "- В Testing refresh-токен обычно истекает через 7 дней; "
            "для постоянной работы нужен Production."
        )
        click.echo("- Запрошенные права: " + ", ".join(SCOPES))
        click.echo("")
        click.echo("Текущее состояние")
        click.echo(f"- OAuth-клиент зашифрован: {'да' if status['oauth_vault_exists'] else 'нет'}")
        click.echo(f"- Токен зашифрован: {'да' if status['token_vault_exists'] else 'нет'}")
        click.echo(f"- ID канала настроен: {'да' if status['channel_id'] else 'нет'}")
