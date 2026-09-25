"""Build authenticated YoutubeService from config + token store."""

from __future__ import annotations

from pathlib import Path

from aiyoutubehands.auth_flow import load_client_secrets, refresh_access_token
from aiyoutubehands.client import HttpClient
from aiyoutubehands.config import load_config
from aiyoutubehands.quota import QuotaEngine
from aiyoutubehands.token import TokenStore
from aiyoutubehands.youtube import YoutubeService


def build_youtube_service(
    *,
    passphrase: str,
    force_quota: bool = False,
) -> tuple[YoutubeService, HttpClient]:
    cfg = load_config()
    if cfg.channel is None or not cfg.channel.expected_channel_id:
        from aiyoutubehands.config import ConfigError

        raise ConfigError(
            "Нужен channel.expected_channel_id",
            code="CONFIG_MISSING_CHANNEL_ID",
        )
    store = TokenStore(path=cfg.auth.token_file, passphrase=passphrase)
    token = store.load()
    if token.is_expired() and token.refresh_token:
        secrets = load_client_secrets(Path(cfg.auth.client_secrets_file))
        token = refresh_access_token(
            str(secrets["client_id"]),
            str(secrets.get("client_secret") or ""),
            token.refresh_token,
        )
        store.save(token)
    client = HttpClient(access_token=token.access_token)
    quota = QuotaEngine(
        db_path=Path(cfg.calendar.db_path).parent / "quota.db",
        daily_limit=cfg.quota.daily_limit,
        force_quota=force_quota or cfg.quota.force_quota,
    )
    yt = YoutubeService(client, quota, cfg.channel.expected_channel_id)
    return yt, client
