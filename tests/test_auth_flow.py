"""Auth flow stub tests."""

from __future__ import annotations

from aiyoutubehands.auth_flow import device_flow_start_stub, device_flow_poll_stub, SCOPES


def test_device_flow_stub() -> None:
    dc = device_flow_start_stub("cid")
    assert dc.user_code
    token = device_flow_poll_stub(dc.device_code)
    assert token.access_token
    assert token.refresh_token
    assert token.scopes == SCOPES
