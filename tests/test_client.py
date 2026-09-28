"""Tests for HTTP client."""

from __future__ import annotations

import pytest
import httpx

from aiyoutubehands.client import (
    HttpClient,
    ClientError,
    CircuitOpenError,
    map_http_error,
)


def test_map_http_error_401() -> None:
    err = map_http_error(401, "Unauthorized")
    assert err.code == "AUTH_REQUIRED"
    assert err.retryable is False


def test_map_http_error_403_quota() -> None:
    err = map_http_error(403, "quotaExceeded")
    assert err.code == "QUOTA_EXCEEDED"
    assert err.retryable is False


def test_map_http_error_429() -> None:
    err = map_http_error(429, "rate limit")
    assert err.code == "RATE_LIMIT"
    assert err.retryable is True


def test_map_http_error_500() -> None:
    err = map_http_error(500, "server error")
    assert err.code == "SERVER_ERROR"
    assert err.retryable is True


def test_circuit_opens_after_failures() -> None:
    client = HttpClient(base_url="https://example.invalid", failure_threshold=3)
    assert client.circuit_closed
    for _ in range(3):
        client._record_failure()
    assert not client.circuit_closed
    with pytest.raises(CircuitOpenError):
        client._ensure_circuit()


def test_circuit_reset() -> None:
    client = HttpClient(base_url="https://example.invalid", failure_threshold=2)
    client._record_failure()
    client._record_failure()
    assert not client.circuit_closed
    client._record_success()
    assert client.circuit_closed


def test_dry_run_bypasses_circuit() -> None:
    client = HttpClient(base_url="https://example.invalid", failure_threshold=1)
    client._record_failure()
    assert not client.circuit_closed
    result = client.get("/whatever", dry_run=True)
    assert result["dry_run"] is True


def test_client_error_retry_after_attr() -> None:
    err = map_http_error(429, "rate")
    assert err.retryable is True
    err.retry_after = 1.5
    assert err.retry_after == 1.5


class _FakeResp401:
    status_code = 401
    text = "Unauthorized"
    headers: dict = {}
    content = b"{}"

    def json(self) -> dict:
        return {}


def test_request_without_token_fails_fast(monkeypatch) -> None:
    """Без токена запрос отвергается до сети, а не падает 401 в середине.

    Регресс: команды полагались на `assert client.access_token`, который под
    `python -O` исчезает, и операция уходила в сеть без авторизации.
    """
    import aiyoutubehands.client as client_mod

    calls: list[str] = []

    class _FakeHTTP:
        def __init__(self, *a, **k): ...

        def request(self, *a, **k):
            calls.append("request")
            return _FakeResp401()

        def close(self): ...

    monkeypatch.setattr(client_mod.httpx, "Client", _FakeHTTP)

    c = HttpClient(base_url="https://example.invalid", access_token="")
    with pytest.raises(ClientError) as ei:
        c.request("POST", "videos", json_body={"id": "x"})

    assert ei.value.code == "NOT_AUTHENTICATED"
    assert calls == []


def test_http_client_ignores_proxy_env(monkeypatch) -> None:
    """Запросы с токеном не должны уходить через прокси из окружения.

    httpx по умолчанию читает HTTP_PROXY/SSL_CERT_FILE и т.п. Для клиента,
    носящего OAuth-токен, это лишний канал утечки.
    """
    import aiyoutubehands.client as client_mod

    captured: list[dict] = []

    class _FakeHTTP:
        def __init__(self, *a, **k):
            captured.append(k)

        def close(self): ...

    monkeypatch.setattr(client_mod.httpx, "Client", _FakeHTTP)

    HttpClient(base_url="https://example.invalid", access_token="x")

    assert captured
    assert captured[0].get("trust_env") is False
