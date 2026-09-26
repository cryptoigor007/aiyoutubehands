"""Auth flow stub tests."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from aiyoutubehands.auth_flow import (
    SCOPES,
    AuthFlowError,
    device_flow_poll_stub,
    device_flow_start_stub,
    desktop_authorization_url,
    load_client_secrets,
)
from aiyoutubehands.token import EncryptedJsonStore


def test_device_flow_stub() -> None:
    dc = device_flow_start_stub("cid")
    assert dc.user_code
    token = device_flow_poll_stub(dc.device_code)
    assert token.access_token
    assert token.refresh_token
    assert token.scopes == SCOPES


def test_load_encrypted_client_secrets(tmp_path: Path) -> None:
    path = tmp_path / "client_secrets.age"
    EncryptedJsonStore(path, passphrase="pass").save(
        {"client_id": "client-id", "client_secret": "client-secret"}
    )
    assert load_client_secrets(path, passphrase="pass")["client_id"] == "client-id"
    with pytest.raises(AuthFlowError):
        load_client_secrets(path, passphrase="wrong")


def test_desktop_authorization_url_uses_pkce_and_local_redirect() -> None:
    url = desktop_authorization_url("client-id", "http://127.0.0.1:9876/", "state-value", "v" * 64)
    query = parse_qs(urlparse(url).query)
    assert query["redirect_uri"] == ["http://127.0.0.1:9876/"]
    assert query["state"] == ["state-value"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["access_type"] == ["offline"]
