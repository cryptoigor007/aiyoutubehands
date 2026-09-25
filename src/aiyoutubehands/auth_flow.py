"""OAuth2 flows (Device Flow + loopback stubs). No real network auth without user action."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiyoutubehands.logging import get_logger
from aiyoutubehands.token import TokenData, TokenStore, TokenError

log = get_logger(__name__)

# Standard YouTube scopes
SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]


@dataclass
class DeviceCodeResponse:
    device_code: str
    user_code: str
    verification_url: str
    expires_in: int
    interval: int


class AuthFlowError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str = "AUTH_FLOW_ERROR",
        action: str = "Проверьте client_secrets",
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.action = action
        self.retryable = retryable


def load_client_secrets(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise AuthFlowError(
            f"Файл client_secrets не найден: {path}",
            code="CLIENT_SECRETS_MISSING",
            action="Скачайте OAuth client JSON из Google Cloud Console",
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    # support both "installed" and "web" formats
    block = data.get("installed") or data.get("web") or data
    if "client_id" not in block:
        raise AuthFlowError("Неверный формат client_secrets", code="CLIENT_SECRETS_INVALID")
    return block


def device_flow_start_stub(client_id: str) -> DeviceCodeResponse:
    """Stub: returns fake device codes for offline testing."""
    log.info("device_flow_start_stub")
    return DeviceCodeResponse(
        device_code="stub_device_code",
        user_code="STUB-CODE",
        verification_url="https://www.google.com/device",
        expires_in=1800,
        interval=5,
    )


def device_flow_poll_stub(device_code: str) -> TokenData:
    """Stub: simulates successful token exchange."""
    log.info("device_flow_poll_stub")
    return TokenData(
        access_token="stub_access_token",
        refresh_token="stub_refresh_token",
        expires_at=int(time.time()) + 3600,
        token_type="Bearer",
        scopes=SCOPES,
    )


def save_token_from_flow(
    token_data: TokenData,
    store: TokenStore,
) -> None:
    store.save(token_data)
    store.audit("login", detail="device_flow_or_loopback")
