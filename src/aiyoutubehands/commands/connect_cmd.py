"""One-command secure YouTube connection."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from aiyoutubehands.commands.auth_cmd import _local_passphrase
from aiyoutubehands.config import load_config_optional, save_channel_id
from aiyoutubehands.token import EncryptedJsonStore, TokenStore


def _find_downloaded_oauth_file(downloads_dir: Path | None = None) -> Path:
    """Return the newest OAuth client download without exposing its contents."""
    downloads = downloads_dir or Path.home() / "Downloads"
    candidates = [
        path
        for pattern in ("client_secret*.json", "client_secrets*.json")
        for path in downloads.glob(pattern)
        if path.is_file()
    ]
    if not candidates:
        raise click.UsageError(
            "Не найден OAuth JSON в Загрузках. "
            "Скачайте OAuth client типа Desktop app из Google Cloud."
        )
    return max(candidates, key=lambda path: path.stat().st_mtime)


def register(cli: click.Group) -> None:
    @cli.command("connect")
    @click.option("--oauth-file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
    @click.option("--channel-id", required=True, help="ID канала, начинается с UC")
    @click.option("--replace", is_flag=True, help="Заменить существующие зашифрованные данные")
    @click.option("--stub", is_flag=True, hidden=True)
    def connect(oauth_file: Path | None, channel_id: str, replace: bool, stub: bool) -> None:
        """Encrypt credentials, configure a channel, and authorize in one flow."""
        from aiyoutubehands.auth_flow import (
            desktop_flow_authorize,
            device_flow_poll_stub,
            device_flow_start_stub,
            read_client_secrets_json,
        )

        if not channel_id.startswith("UC"):
            raise click.UsageError("--channel-id должен начинаться с UC")

        oauth_file = oauth_file or _find_downloaded_oauth_file()
        client_secrets = read_client_secrets_json(oauth_file)
        cfg = load_config_optional()
        oauth_vault = Path(cfg.auth.client_secrets_file)
        token_vault = Path(cfg.auth.token_file)
        if (oauth_vault.is_file() or token_vault.is_file()) and not replace:
            click.echo("Подключение уже настроено. Для замены передайте --replace.")
            sys.exit(2)

        passphrase = _local_passphrase(None, confirm=True)
        EncryptedJsonStore(oauth_vault, passphrase=passphrase).save(client_secrets)
        config_path = save_channel_id(channel_id)
        oauth_file.unlink()
        click.echo("OAuth-данные зашифрованы, JSON из Загрузок удалён, канал настроен.")

        if stub:
            token = device_flow_poll_stub(device_flow_start_stub("stub").device_code)
        else:
            click.echo("Откроется системный браузер. Выберите аккаунт с нужным каналом.")
            token = desktop_flow_authorize(
                str(client_secrets["client_id"]), str(client_secrets.get("client_secret") or "")
            )
        TokenStore(token_vault, passphrase=passphrase).save(token)
        click.echo(f"Подключение готово. Конфигурация: {config_path}")
