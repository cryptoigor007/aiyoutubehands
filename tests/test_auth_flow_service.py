"""Tests for ``auth_flow`` helpers and ``service_factory`` wiring.

Everything external is mocked:

* HTTP goes through ``respx`` — no socket ever leaves the process;
* ``webbrowser.open`` and ``HTTPServer`` are replaced with in-process fakes,
  so the loopback desktop flow never binds a real port or opens a browser;
* ``time.sleep`` is neutralised, so device-flow polling tests are instant.

Every test function is annotated ``-> None`` and there are no ``assert True``.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
import yaml

import aiyoutubehands.auth_flow as auth_flow
from aiyoutubehands.auth_flow import (
    AUTHORIZATION_URL,
    DEVICE_CODE_URL,
    SCOPES,
    TOKEN_URL,
    AuthFlowError,
    desktop_authorization_url,
    desktop_flow_authorize,
    device_flow_poll,
    device_flow_poll_stub,
    device_flow_start,
    device_flow_start_stub,
    load_client_secrets,
    read_client_secrets_json,
    refresh_access_token,
    save_token_from_flow,
)
from aiyoutubehands.config import ConfigError
from aiyoutubehands.service_factory import build_youtube_service
from aiyoutubehands.token import EncryptedJsonStore, TokenData, TokenError, TokenStore

if TYPE_CHECKING:
    from pathlib import Path

# --------------------------------------------------------------------------- #
# Fakes: loopback server + browser (desktop_flow_authorize)
# --------------------------------------------------------------------------- #


class _FakeHTTPServer:
    """Stand-in for ``http.server.HTTPServer`` that never binds a port.

    On the first ``handle_request`` it runs the real callback handler class with
    a synthetic ``GET`` path, which is exactly how the real server would invoke
    it when the browser hits the redirect URI.
    """

    def __init__(self, address: tuple[str, int], handler_cls: type[Any], holder: dict[str, Any]):
        self.address = address
        self.handler_cls = handler_cls
        self.holder = holder
        self.server_port = 45678
        self.timeout = 0.0
        self.closed = False
        self.calls = 0

    def handle_request(self) -> None:
        self.calls += 1
        if self.calls > 1:
            # Guard against an accidental busy loop if the fake callback did
            # not populate ``received``; failing fast beats hanging.
            raise RuntimeError("fake server asked for a second request")
        handler = object.__new__(self.handler_cls)
        handler.path = self.holder["path"]
        handler.wfile = io.BytesIO()
        handler.request_version = "HTTP/1.1"
        handler.command = "GET"
        handler.close_connection = True
        handler.requestline = f"GET {handler.path} HTTP/1.1"
        handler.client_address = ("127.0.0.1", 54321)
        self.handler_cls.do_GET(handler)

    def server_close(self) -> None:
        self.closed = True


def _install_fake_server(monkeypatch: pytest.MonkeyPatch, holder: dict[str, Any]) -> dict[str, Any]:
    def factory(address: tuple[str, int], handler_cls: type[Any]) -> _FakeHTTPServer:
        server = _FakeHTTPServer(address, handler_cls, holder)
        holder["server"] = server
        return server

    monkeypatch.setattr(auth_flow, "HTTPServer", factory)
    return holder


def _install_fake_browser(
    monkeypatch: pytest.MonkeyPatch,
    holder: dict[str, Any],
    opened: list[str],
    *,
    result: bool = True,
    marker: str = "code",
) -> None:
    def fake_open(url: str) -> bool:
        opened.append(url)
        query = parse_qs(urlparse(url).query)
        state = query["state"][0]
        if marker == "code":
            holder["path"] = f"/?code=AUTH_CODE&state={state}"
        elif marker == "bad_state":
            holder["path"] = "/?code=AUTH_CODE&state=not-the-state"
        elif marker == "error":
            holder["path"] = f"/?error=access_denied&state={state}"
        else:  # "none" — simulate a callback that never arrives
            holder["path"] = "/?ignored=1"
        return result

    monkeypatch.setattr(auth_flow.webbrowser, "open", fake_open)


class _SleepRecorder:
    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


# --------------------------------------------------------------------------- #
# read_client_secrets_json / client-secrets validation
# --------------------------------------------------------------------------- #


def test_read_client_secrets_json_installed_block(tmp_path: Path) -> None:
    path = tmp_path / "client_secret.json"
    path.write_text(
        json.dumps({"installed": {"client_id": "cid", "client_secret": "sec"}}),
        encoding="utf-8",
    )
    block = read_client_secrets_json(path)
    assert block["client_id"] == "cid"
    assert block["client_secret"] == "sec"


def test_read_client_secrets_json_web_block(tmp_path: Path) -> None:
    path = tmp_path / "client_secret.json"
    path.write_text(json.dumps({"web": {"client_id": "web-cid"}}), encoding="utf-8")
    assert read_client_secrets_json(path)["client_id"] == "web-cid"


def test_read_client_secrets_json_top_level_client_id(tmp_path: Path) -> None:
    path = tmp_path / "client_secret.json"
    path.write_text(json.dumps({"client_id": "bare-cid"}), encoding="utf-8")
    assert read_client_secrets_json(path)["client_id"] == "bare-cid"


def test_read_client_secrets_json_missing_file(tmp_path: Path) -> None:
    with pytest.raises(AuthFlowError) as exc:
        read_client_secrets_json(tmp_path / "nope.json")
    assert exc.value.code == "CLIENT_SECRETS_MISSING"


def test_read_client_secrets_json_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "client_secret.json"
    path.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(AuthFlowError) as exc:
        read_client_secrets_json(path)
    assert exc.value.code == "CLIENT_SECRETS_INVALID"


def test_read_client_secrets_json_non_dict(tmp_path: Path) -> None:
    path = tmp_path / "client_secret.json"
    path.write_text(json.dumps(["a", "b"]), encoding="utf-8")
    with pytest.raises(AuthFlowError) as exc:
        read_client_secrets_json(path)
    assert exc.value.code == "CLIENT_SECRETS_INVALID"


def test_read_client_secrets_json_block_without_client_id(tmp_path: Path) -> None:
    path = tmp_path / "client_secret.json"
    path.write_text(json.dumps({"installed": {"project_id": "p"}}), encoding="utf-8")
    with pytest.raises(AuthFlowError) as exc:
        read_client_secrets_json(path)
    assert exc.value.code == "CLIENT_SECRETS_INVALID"


def test_load_client_secrets_missing_file(tmp_path: Path) -> None:
    with pytest.raises(AuthFlowError) as exc:
        load_client_secrets(tmp_path / "client_secrets.age", passphrase="pass")
    assert exc.value.code == "CLIENT_SECRETS_MISSING"


def test_validate_client_secrets_rejects_non_dict_block() -> None:
    with pytest.raises(AuthFlowError) as exc:
        auth_flow._validate_client_secrets({"installed": "not-a-dict"})
    assert exc.value.code == "CLIENT_SECRETS_INVALID"


# --------------------------------------------------------------------------- #
# desktop_authorization_url / PKCE
# --------------------------------------------------------------------------- #


def test_desktop_authorization_url_pkce_s256_challenge() -> None:
    verifier = "verifier-value-" + "x" * 50
    url = desktop_authorization_url("cid", "http://127.0.0.1:9999/", "state-1", verifier)
    query = parse_qs(urlparse(url).query)
    assert url.startswith(AUTHORIZATION_URL + "?")
    assert query["client_id"] == ["cid"]
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert query["scope"] == [" ".join(SCOPES)]
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .decode("ascii")
        .rstrip("=")
    )
    assert query["code_challenge"] == [expected]


def test_desktop_authorization_url_custom_scopes() -> None:
    url = desktop_authorization_url(
        "cid", "http://127.0.0.1:1/", "s", "v", scopes=["scope.one", "scope.two"]
    )
    assert parse_qs(urlparse(url).query)["scope"] == ["scope.one scope.two"]


# --------------------------------------------------------------------------- #
# device_flow_start
# --------------------------------------------------------------------------- #


@respx.mock
def test_device_flow_start_success() -> None:
    route = respx.post(DEVICE_CODE_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "device_code": "dev-code",
                "user_code": "USER-CODE",
                "verification_url": "https://example.test/device",
                "expires_in": 120,
                "interval": 3,
            },
        )
    )
    result = device_flow_start("cid")
    assert result.device_code == "dev-code"
    assert result.user_code == "USER-CODE"
    assert result.verification_url == "https://example.test/device"
    assert result.expires_in == 120
    assert result.interval == 3
    body = parse_qs(route.calls[0].request.content.decode())
    assert body["client_id"] == ["cid"]
    assert body["scope"] == [" ".join(SCOPES)]


@respx.mock
def test_device_flow_start_verification_uri_fallback_and_custom_scopes() -> None:
    route = respx.post(DEVICE_CODE_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "device_code": "d",
                "user_code": "u",
                "verification_uri": "https://fallback.test",
            },
        )
    )
    result = device_flow_start("cid", scopes=["only.one"])
    assert result.verification_url == "https://fallback.test"
    assert result.expires_in == 1800  # default
    assert result.interval == 5  # default
    body = parse_qs(route.calls[0].request.content.decode())
    assert body["scope"] == ["only.one"]


@respx.mock
def test_device_flow_start_http_error() -> None:
    respx.post(DEVICE_CODE_URL).mock(return_value=httpx.Response(500, text="boom"))
    with pytest.raises(AuthFlowError) as exc:
        device_flow_start("cid")
    assert exc.value.code == "DEVICE_CODE_FAILED"
    assert exc.value.retryable is True


# --------------------------------------------------------------------------- #
# device_flow_poll
# --------------------------------------------------------------------------- #


def _token_response(*, access: str = "ACCESS", refresh: str = "REFRESH") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "access_token": access,
            "refresh_token": refresh,
            "expires_in": 1200,
            "token_type": "Bearer",
            "scope": "a b",
        },
    )


@respx.mock
def test_device_flow_poll_success(monkeypatch: pytest.MonkeyPatch) -> None:
    sleep = _SleepRecorder()
    monkeypatch.setattr(auth_flow.time, "sleep", sleep)
    respx.post(TOKEN_URL).mock(return_value=_token_response())
    token = device_flow_poll("cid", "sec", "dev-code", interval=1, expires_in=30)
    assert token.access_token == "ACCESS"
    assert token.refresh_token == "REFRESH"
    assert token.scopes == ["a", "b"]
    assert token.expires_at > int(time.time())
    assert sleep.calls == []  # succeeded on the first poll, no waiting


@respx.mock
def test_device_flow_poll_authorization_pending_then_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleep = _SleepRecorder()
    monkeypatch.setattr(auth_flow.time, "sleep", sleep)
    respx.post(TOKEN_URL).mock(
        side_effect=[
            httpx.Response(400, json={"error": "authorization_pending"}),
            _token_response(access="SECOND"),
        ]
    )
    token = device_flow_poll("cid", "sec", "dev-code", interval=2, expires_in=30)
    assert token.access_token == "SECOND"
    assert sleep.calls == [2]


@respx.mock
def test_device_flow_poll_slow_down_increases_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleep = _SleepRecorder()
    monkeypatch.setattr(auth_flow.time, "sleep", sleep)
    respx.post(TOKEN_URL).mock(
        side_effect=[
            httpx.Response(400, json={"error": "slow_down"}),
            _token_response(access="SLOW"),
        ]
    )
    token = device_flow_poll("cid", "sec", "dev-code", interval=5, expires_in=30)
    assert token.access_token == "SLOW"
    # wait starts at 5, slow_down bumps it by 5 before sleeping.
    assert sleep.calls == [10]


@pytest.mark.parametrize("error", ["access_denied", "expired_token"])
@respx.mock
def test_device_flow_poll_denied_and_expired(error: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_flow.time, "sleep", _SleepRecorder())
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(400, json={"error": error}))
    with pytest.raises(AuthFlowError) as exc:
        device_flow_poll("cid", "sec", "dev-code", interval=1, expires_in=30)
    assert exc.value.code == "AUTH_DENIED"


@respx.mock
def test_device_flow_poll_unexpected_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_flow.time, "sleep", _SleepRecorder())
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))
    with pytest.raises(AuthFlowError) as exc:
        device_flow_poll("cid", "sec", "dev-code", interval=1, expires_in=30)
    assert exc.value.code == "TOKEN_POLL_FAILED"
    assert exc.value.retryable is True


def test_device_flow_poll_immediate_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    sleep = _SleepRecorder()
    monkeypatch.setattr(auth_flow.time, "sleep", sleep)
    with pytest.raises(AuthFlowError) as exc:
        device_flow_poll("cid", "sec", "dev-code", interval=1, expires_in=0)
    assert exc.value.code == "AUTH_TIMEOUT"
    assert sleep.calls == []


# --------------------------------------------------------------------------- #
# stub flows + save_token_from_flow
# --------------------------------------------------------------------------- #


def test_device_flow_stubs() -> None:
    start = device_flow_start_stub("cid")
    assert start.device_code == "stub_device_code"
    assert start.user_code == "STUB-CODE"
    polled = device_flow_poll_stub(start.device_code)
    assert polled.access_token == "stub_access_token"
    assert polled.refresh_token == "stub_refresh_token"
    assert polled.token_type == "Bearer"


def test_save_token_from_flow_writes_and_audits(tmp_path: Path) -> None:
    store = TokenStore(tmp_path / "token.age", key=b"k" * 32)
    data = TokenData(access_token="at", refresh_token="rt", expires_at=int(time.time()) + 60)
    save_token_from_flow(data, store)
    assert store.load().access_token == "at"
    audit = (tmp_path / "token.audit.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert any('"login"' in line for line in audit)


# --------------------------------------------------------------------------- #
# refresh_access_token
# --------------------------------------------------------------------------- #


@respx.mock
def test_refresh_access_token_success() -> None:
    route = respx.post(TOKEN_URL).mock(return_value=_token_response(access="NEW"))
    token = refresh_access_token("cid", "sec", "old-refresh")
    assert token.access_token == "NEW"
    assert token.refresh_token == "old-refresh"  # preserved when server omits it
    body = parse_qs(route.calls[0].request.content.decode())
    assert body["grant_type"] == ["refresh_token"]
    assert body["refresh_token"] == ["old-refresh"]


@respx.mock
def test_refresh_access_token_failure() -> None:
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(400, text="bad"))
    with pytest.raises(AuthFlowError) as exc:
        refresh_access_token("cid", "sec", "rt")
    assert exc.value.code == "REFRESH_FAILED"
    assert exc.value.retryable is True


# --------------------------------------------------------------------------- #
# desktop_flow_authorize (loopback flow, fully faked)
# --------------------------------------------------------------------------- #


def test_desktop_flow_browser_open_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    holder: dict[str, Any] = {}
    _install_fake_server(monkeypatch, holder)
    opened: list[str] = []
    _install_fake_browser(monkeypatch, holder, opened, result=False)
    with pytest.raises(AuthFlowError) as exc:
        desktop_flow_authorize("cid", "sec", timeout=1)
    assert exc.value.code == "BROWSER_OPEN_FAILED"
    assert len(opened) == 1
    assert holder["server"].closed is True


def test_desktop_flow_timeout_without_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    holder: dict[str, Any] = {}
    _install_fake_server(monkeypatch, holder)
    opened: list[str] = []
    _install_fake_browser(monkeypatch, holder, opened, marker="none")
    with pytest.raises(AuthFlowError) as exc:
        desktop_flow_authorize("cid", "sec", timeout=0)
    assert exc.value.code == "AUTH_TIMEOUT"
    assert holder["server"].closed is True


def test_desktop_flow_state_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    holder: dict[str, Any] = {}
    _install_fake_server(monkeypatch, holder)
    opened: list[str] = []
    _install_fake_browser(monkeypatch, holder, opened, marker="bad_state")
    with pytest.raises(AuthFlowError) as exc:
        desktop_flow_authorize("cid", "sec", timeout=5)
    assert exc.value.code == "AUTH_TIMEOUT"


@respx.mock
def test_desktop_flow_success_exchanges_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    holder: dict[str, Any] = {}
    _install_fake_server(monkeypatch, holder)
    opened: list[str] = []
    _install_fake_browser(monkeypatch, holder, opened, marker="code")
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "ACCESS",
                "refresh_token": "REFRESH",
                "expires_in": 600,
                "token_type": "Bearer",
                "scope": "x y",
            },
        )
    )
    token = desktop_flow_authorize("cid", "sec", timeout=5)
    assert token.access_token == "ACCESS"
    assert token.refresh_token == "REFRESH"
    assert token.scopes == ["x", "y"]
    assert token.token_type == "Bearer"
    assert len(opened) == 1
    auth_query = parse_qs(urlparse(opened[0]).query)
    assert auth_query["code_challenge_method"] == ["S256"]
    assert auth_query["state"][0]
    body = parse_qs(route.calls[0].request.content.decode())
    assert body["grant_type"] == ["authorization_code"]
    assert body["code"] == ["AUTH_CODE"]
    assert body["code_verifier"][0]


@respx.mock
def test_desktop_flow_denied_by_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    holder: dict[str, Any] = {}
    _install_fake_server(monkeypatch, holder)
    opened: list[str] = []
    _install_fake_browser(monkeypatch, holder, opened, marker="error")
    with pytest.raises(AuthFlowError) as exc:
        desktop_flow_authorize("cid", "sec", timeout=5)
    assert exc.value.code == "AUTH_DENIED"


@respx.mock
def test_desktop_flow_token_exchange_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    holder: dict[str, Any] = {}
    _install_fake_server(monkeypatch, holder)
    opened: list[str] = []
    _install_fake_browser(monkeypatch, holder, opened, marker="code")
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(400, text="nope"))
    with pytest.raises(AuthFlowError) as exc:
        desktop_flow_authorize("cid", "sec", timeout=5)
    assert exc.value.code == "TOKEN_EXCHANGE_FAILED"
    assert exc.value.retryable is True


# --------------------------------------------------------------------------- #
# service_factory.build_youtube_service
# --------------------------------------------------------------------------- #

_PASSPHRASE = "test-passphrase"


def _write_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    token_file: Path,
    client_secrets_file: Path,
    calendar_db: Path,
    channel: str | None = "UC-test-channel-0001",
    daily_limit: int = 10000,
    force_quota: bool = False,
) -> Path:
    config_root = tmp_path / "xdg-config"
    config_dir = config_root / "aiyoutubehands"
    config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_root))
    data: dict[str, Any] = {
        "auth": {
            "token_file": str(token_file),
            "client_secrets_file": str(client_secrets_file),
        },
        "quota": {"daily_limit": daily_limit, "force_quota": force_quota},
        "calendar": {"db_path": str(calendar_db)},
    }
    if channel is not None:
        data["channel"] = {"expected_channel_id": channel}
    (config_dir / "config.yaml").write_text(
        yaml.safe_dump(data, allow_unicode=True), encoding="utf-8"
    )
    return config_dir


def test_build_youtube_service_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    token_file = tmp_path / "secrets" / "token.age"
    secrets_file = tmp_path / "secrets" / "client_secrets.age"
    calendar_db = tmp_path / "state" / "calendar.db"
    _write_config(
        tmp_path,
        monkeypatch,
        token_file=token_file,
        client_secrets_file=secrets_file,
        calendar_db=calendar_db,
        daily_limit=7777,
    )
    TokenStore(token_file, passphrase=_PASSPHRASE).save(
        TokenData(
            access_token="live-token",
            refresh_token="live-refresh",
            expires_at=int(time.time()) + 3600,
        )
    )

    yt, client = build_youtube_service(passphrase=_PASSPHRASE)

    assert client.access_token == "live-token"
    assert yt.expected_channel_id == "UC-test-channel-0001"
    assert yt.quota.daily_limit == 7777
    # quota.db must be a sibling of the configured calendar.db.
    assert yt.quota.ledger.db_path == calendar_db.parent / "quota.db"
    assert yt.quota.ledger.db_path.exists()


def test_build_youtube_service_force_quota_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token_file = tmp_path / "token.age"
    secrets_file = tmp_path / "client_secrets.age"
    calendar_db = tmp_path / "state" / "calendar.db"
    _write_config(
        tmp_path,
        monkeypatch,
        token_file=token_file,
        client_secrets_file=secrets_file,
        calendar_db=calendar_db,
    )
    TokenStore(token_file, passphrase=_PASSPHRASE).save(
        TokenData(access_token="t", expires_at=int(time.time()) + 3600)
    )
    yt, _ = build_youtube_service(passphrase=_PASSPHRASE, force_quota=True)
    assert yt.quota.force_quota is True


def test_build_youtube_service_reads_force_quota_from_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token_file = tmp_path / "token.age"
    secrets_file = tmp_path / "client_secrets.age"
    calendar_db = tmp_path / "state" / "calendar.db"
    _write_config(
        tmp_path,
        monkeypatch,
        token_file=token_file,
        client_secrets_file=secrets_file,
        calendar_db=calendar_db,
        force_quota=True,
    )
    TokenStore(token_file, passphrase=_PASSPHRASE).save(
        TokenData(access_token="t", expires_at=int(time.time()) + 3600)
    )
    yt, _ = build_youtube_service(passphrase=_PASSPHRASE)
    assert yt.quota.force_quota is True


@respx.mock
def test_build_youtube_service_refreshes_expired_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token_file = tmp_path / "secrets" / "token.age"
    secrets_file = tmp_path / "secrets" / "client_secrets.age"
    calendar_db = tmp_path / "state" / "calendar.db"
    _write_config(
        tmp_path,
        monkeypatch,
        token_file=token_file,
        client_secrets_file=secrets_file,
        calendar_db=calendar_db,
    )
    EncryptedJsonStore(secrets_file, passphrase=_PASSPHRASE).save(
        {"installed": {"client_id": "cid", "client_secret": "csec"}}
    )
    expired = TokenData(
        access_token="stale",
        refresh_token="rt",
        expires_at=int(time.time()) - 100,
    )
    TokenStore(token_file, passphrase=_PASSPHRASE).save(expired)

    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "fresh", "expires_in": 3600})
    )

    yt, client = build_youtube_service(passphrase=_PASSPHRASE)

    assert client.access_token == "fresh"
    assert yt.client.access_token == "fresh"
    saved = TokenStore(token_file, passphrase=_PASSPHRASE).load()
    assert saved.access_token == "fresh"
    assert saved.refresh_token == "rt"
    body = parse_qs(route.calls[0].request.content.decode())
    assert body["client_id"] == ["cid"]
    assert body["refresh_token"] == ["rt"]


def test_build_youtube_service_missing_channel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token_file = tmp_path / "token.age"
    secrets_file = tmp_path / "client_secrets.age"
    calendar_db = tmp_path / "state" / "calendar.db"
    _write_config(
        tmp_path,
        monkeypatch,
        token_file=token_file,
        client_secrets_file=secrets_file,
        calendar_db=calendar_db,
        channel=None,
    )
    with pytest.raises(ConfigError) as exc:
        build_youtube_service(passphrase=_PASSPHRASE)
    assert exc.value.code == "CONFIG_MISSING_CHANNEL_ID"


def test_build_youtube_service_missing_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token_file = tmp_path / "does-not-exist.age"
    secrets_file = tmp_path / "client_secrets.age"
    calendar_db = tmp_path / "state" / "calendar.db"
    _write_config(
        tmp_path,
        monkeypatch,
        token_file=token_file,
        client_secrets_file=secrets_file,
        calendar_db=calendar_db,
    )
    with pytest.raises(TokenError) as exc:
        build_youtube_service(passphrase=_PASSPHRASE)
    assert exc.value.code == "TOKEN_NOT_FOUND"


@respx.mock
def test_build_youtube_service_refresh_failure_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token_file = tmp_path / "secrets" / "token.age"
    secrets_file = tmp_path / "secrets" / "client_secrets.age"
    calendar_db = tmp_path / "state" / "calendar.db"
    _write_config(
        tmp_path,
        monkeypatch,
        token_file=token_file,
        client_secrets_file=secrets_file,
        calendar_db=calendar_db,
    )
    EncryptedJsonStore(secrets_file, passphrase=_PASSPHRASE).save({"client_id": "cid"})
    TokenStore(token_file, passphrase=_PASSPHRASE).save(
        TokenData(access_token="stale", refresh_token="rt", expires_at=int(time.time()) - 100)
    )
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(400, text="denied"))
    with pytest.raises(AuthFlowError) as exc:
        build_youtube_service(passphrase=_PASSPHRASE)
    assert exc.value.code == "REFRESH_FAILED"


def test_expired_token_without_refresh_is_rejected(tmp_path, monkeypatch) -> None:
    """Просроченный токен без refresh_token — понятная ошибка сразу.

    Регресс: условие `is_expired() and refresh_token` пропускало такой токен
    дальше, и клиент создавался с протухшим access_token — ошибка всплывала
    позже как невнятный 401 в произвольной операции.
    """
    from aiyoutubehands.service_factory import build_youtube_service
    from aiyoutubehands.token import TokenData, TokenStore

    cfg_base = tmp_path / "config"
    cfg_dir = cfg_base / "aiyoutubehands"
    cfg_dir.mkdir(parents=True)
    token_path = cfg_dir / "token.age"
    (cfg_dir / "config.yaml").write_text(
        f"channel:\n  expected_channel_id: UC_test\nauth:\n  token_file: {token_path}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg_base))

    TokenStore(path=token_path, passphrase="pw").save(
        TokenData(access_token="stale", refresh_token="", expires_at=1)
    )

    with pytest.raises(Exception) as ei:
        build_youtube_service(passphrase="pw")

    assert getattr(ei.value, "code", "") == "TOKEN_EXPIRED_NO_REFRESH"
