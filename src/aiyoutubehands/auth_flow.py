"""OAuth2 Device Flow + helpers for YouTube API."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from aiyoutubehands.logging import get_logger
from aiyoutubehands.token import TokenData, TokenStore

log = get_logger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"


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


@dataclass
class DeviceCodeResponse:
    device_code: str
    user_code: str
    verification_url: str
    expires_in: int
    interval: int


def load_client_secrets(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise AuthFlowError(
            f"Файл client_secrets не найден: {path}",
            code="CLIENT_SECRETS_MISSING",
            action="Скачайте OAuth client JSON (Desktop/TV) из Google Cloud Console",
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    block = data.get("installed") or data.get("web") or data
    if "client_id" not in block:
        raise AuthFlowError("Неверный формат client_secrets", code="CLIENT_SECRETS_INVALID")
    return block


def device_flow_start(client_id: str, *, scopes: list[str] | None = None) -> DeviceCodeResponse:
    """Start Google OAuth Device Authorization Grant."""
    scope = " ".join(scopes or SCOPES)
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            DEVICE_CODE_URL,
            data={"client_id": client_id, "scope": scope},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if resp.status_code >= 400:
        raise AuthFlowError(
            f"device/code failed: {resp.status_code} {resp.text[:300]}",
            code="DEVICE_CODE_FAILED",
            retryable=True,
        )
    data = resp.json()
    return DeviceCodeResponse(
        device_code=str(data["device_code"]),
        user_code=str(data["user_code"]),
        verification_url=str(
            data.get("verification_url") or data.get("verification_uri") or "https://www.google.com/device"
        ),
        expires_in=int(data.get("expires_in", 1800)),
        interval=int(data.get("interval", 5)),
    )


def device_flow_poll(
    client_id: str,
    client_secret: str,
    device_code: str,
    *,
    interval: int = 5,
    expires_in: int = 1800,
) -> TokenData:
    """Poll token endpoint until user completes device login or timeout."""
    deadline = time.time() + expires_in
    wait = max(1, interval)
    with httpx.Client(timeout=30.0) as client:
        while time.time() < deadline:
            resp = client.post(
                TOKEN_URL,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            data = resp.json() if resp.content else {}
            if resp.status_code == 200 and "access_token" in data:
                expires_at = int(time.time()) + int(data.get("expires_in", 3600))
                return TokenData(
                    access_token=str(data["access_token"]),
                    refresh_token=str(data.get("refresh_token") or ""),
                    expires_at=expires_at,
                    token_type=str(data.get("token_type") or "Bearer"),
                    scopes=str(data.get("scope") or "").split(),
                )
            err = str(data.get("error") or "")
            if err == "authorization_pending":
                time.sleep(wait)
                continue
            if err == "slow_down":
                wait += 5
                time.sleep(wait)
                continue
            if err in {"access_denied", "expired_token"}:
                raise AuthFlowError(
                    f"Авторизация отклонена или истекла: {err}",
                    code="AUTH_DENIED",
                )
            raise AuthFlowError(
                f"token poll failed: {resp.status_code} {data}",
                code="TOKEN_POLL_FAILED",
                retryable=True,
            )
    raise AuthFlowError("Таймаут ожидания авторизации", code="AUTH_TIMEOUT")


def refresh_access_token(
    client_id: str,
    client_secret: str,
    refresh_token: str,
) -> TokenData:
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if resp.status_code >= 400:
        raise AuthFlowError(
            f"refresh failed: {resp.status_code} {resp.text[:300]}",
            code="REFRESH_FAILED",
            retryable=True,
        )
    data = resp.json()
    return TokenData(
        access_token=str(data["access_token"]),
        refresh_token=refresh_token,
        expires_at=int(time.time()) + int(data.get("expires_in", 3600)),
        token_type=str(data.get("token_type") or "Bearer"),
        scopes=str(data.get("scope") or "").split(),
    )


def device_flow_start_stub(client_id: str) -> DeviceCodeResponse:
    log.info("device_flow_start_stub")
    return DeviceCodeResponse(
        device_code="stub_device_code",
        user_code="STUB-CODE",
        verification_url="https://www.google.com/device",
        expires_in=1800,
        interval=5,
    )


def device_flow_poll_stub(device_code: str) -> TokenData:
    log.info("device_flow_poll_stub")
    return TokenData(
        access_token="stub_access_token",
        refresh_token="stub_refresh_token",
        expires_at=int(time.time()) + 3600,
        token_type="Bearer",
        scopes=SCOPES,
    )


def save_token_from_flow(token_data: TokenData, store: TokenStore) -> None:
    store.save(token_data)
    store.audit("login", detail="device_flow")
