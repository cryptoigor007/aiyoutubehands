"""OAuth2 helpers for YouTube API."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from aiyoutubehands.logging import get_logger
from aiyoutubehands.token import EncryptedJsonStore, TokenData, TokenError, TokenStore

log = get_logger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"


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


def _validate_client_secrets(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise AuthFlowError("Неверный формат client_secrets", code="CLIENT_SECRETS_INVALID")
    block = data.get("installed") or data.get("web") or data
    if not isinstance(block, dict) or "client_id" not in block:
        raise AuthFlowError("Неверный формат client_secrets", code="CLIENT_SECRETS_INVALID")
    return block


def read_client_secrets_json(path: Path) -> dict[str, Any]:
    """Read the one-time JSON download before it is encrypted locally."""
    if not path.is_file():
        raise AuthFlowError(
            f"Файл client_secrets не найден: {path}",
            code="CLIENT_SECRETS_MISSING",
            action="Скачайте OAuth client JSON из Google Cloud Console",
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise AuthFlowError(
            "Не удалось прочитать JSON OAuth-клиента", code="CLIENT_SECRETS_INVALID"
        ) from exc
    return _validate_client_secrets(data)


def load_client_secrets(path: Path, *, passphrase: str) -> dict[str, Any]:
    """Load OAuth client metadata from the encrypted local vault."""
    try:
        return _validate_client_secrets(EncryptedJsonStore(path, passphrase=passphrase).load())
    except TokenError as exc:
        raise AuthFlowError(exc.message, code=exc.code, action=exc.action) from exc


def desktop_authorization_url(
    client_id: str,
    redirect_uri: str,
    state: str,
    code_verifier: str,
    *,
    scopes: list[str] | None = None,
) -> str:
    """Build an installed-app OAuth URL with PKCE."""
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest())
        .decode("ascii")
        .rstrip("=")
    )
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes or SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{AUTHORIZATION_URL}?{query}"


def desktop_flow_authorize(
    client_id: str,
    client_secret: str,
    *,
    scopes: list[str] | None = None,
    timeout: int = 300,
) -> TokenData:
    """Authorize an installed app through the system browser and loopback redirect."""
    received: dict[str, str] = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            params = parse_qs(urlparse(self.path).query)
            for key in ("code", "state", "error"):
                if params.get(key):
                    received[key] = params[key][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            message = (
                "<html><body><p>Авторизация завершена. "
                "Можно закрыть это окно.</p></body></html>"
            )
            self.wfile.write(message.encode("utf-8"))

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), CallbackHandler)
    server.timeout = 1.0
    redirect_uri = f"http://127.0.0.1:{server.server_port}/"
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    url = desktop_authorization_url(client_id, redirect_uri, state, verifier, scopes=scopes)
    try:
        if not webbrowser.open(url):
            raise AuthFlowError(
                "Не удалось открыть системный браузер",
                code="BROWSER_OPEN_FAILED",
                action="Откройте приложение в обычном сеансе macOS и повторите вход",
            )
        deadline = time.time() + timeout
        while time.time() < deadline and not received:
            server.handle_request()
    finally:
        server.server_close()

    if received.get("error"):
        raise AuthFlowError(f"Авторизация отклонена: {received['error']}", code="AUTH_DENIED")
    if received.get("state") != state or not received.get("code"):
        raise AuthFlowError("Таймаут или неверный ответ авторизации", code="AUTH_TIMEOUT")

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": received["code"],
                "code_verifier": verifier,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    if resp.status_code >= 400:
        raise AuthFlowError(
            f"Обмен кода авторизации не удался: {resp.status_code}",
            code="TOKEN_EXCHANGE_FAILED",
            retryable=True,
        )
    data = resp.json()
    return TokenData(
        access_token=str(data["access_token"]),
        refresh_token=str(data.get("refresh_token") or ""),
        expires_at=int(time.time()) + int(data.get("expires_in", 3600)),
        token_type=str(data.get("token_type") or "Bearer"),
        scopes=str(data.get("scope") or "").split(),
    )


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
            data.get("verification_url")
            or data.get("verification_uri")
            or "https://www.google.com/device"
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
