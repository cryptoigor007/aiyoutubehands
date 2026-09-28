"""Real network-path tests for :mod:`aiyoutubehands.client`.

Everything here goes through ``respx`` so the suite never opens a socket.
The companion ``tests/test_client.py`` exercises the pure helpers
(``map_http_error`` codes, circuit counter arithmetic); this file drives
``HttpClient.request`` end to end: methods, retries, ``Retry-After``,
transport failures and the circuit breaker.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import pytest
import respx

import aiyoutubehands.client as client_mod
from aiyoutubehands.client import (
    CircuitOpenError,
    ClientError,
    HttpClient,
    map_http_error,
)

BASE = "https://api.test/youtube/v3"
TOKEN = "access-token"


def _make_client(**kwargs: Any) -> HttpClient:
    kwargs.setdefault("base_url", BASE)
    kwargs.setdefault("access_token", TOKEN)
    return HttpClient(**kwargs)


@pytest.fixture
def sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Capture backoff delays instead of blocking the suite for real seconds."""
    calls: list[float] = []

    def _fake_sleep(seconds: float) -> None:
        calls.append(seconds)

    monkeypatch.setattr(client_mod.time, "sleep", _fake_sleep)
    return calls


# ---------------------------------------------------------------------------
# map_http_error — detailed bodies
# ---------------------------------------------------------------------------


def test_map_http_error_reads_reason_from_json_errors() -> None:
    body = '{"error": {"errors": [{"reason": "quotaExceeded"}], "message": "quota"}}'
    err = map_http_error(403, body)
    assert err.code == "QUOTA_EXCEEDED"
    assert err.status_code == 403
    assert err.retryable is False


def test_map_http_error_daily_limit_reason_is_quota() -> None:
    body = '{"error": {"errors": [{"reason": "dailyLimitExceeded"}]}}'
    assert map_http_error(403, body).code == "QUOTA_EXCEEDED"


def test_map_http_error_403_plain_text_quota() -> None:
    """Text bodies are scanned case-insensitively for the word quota."""
    err = map_http_error(403, "The request cannot be completed, Quota exceeded")
    assert err.code == "QUOTA_EXCEEDED"


def test_map_http_error_403_without_quota_is_forbidden() -> None:
    body = '{"error": {"errors": [{"reason": "forbidden"}], "message": "no"}}'
    err = map_http_error(403, body)
    assert err.code == "FORBIDDEN"
    assert err.status_code == 403
    assert err.retryable is False


def test_map_http_error_invalid_json_body_does_not_crash() -> None:
    err = map_http_error(403, "{not valid json at all")
    assert err.code == "FORBIDDEN"


def test_map_http_error_error_list_without_dicts() -> None:
    """``errors`` may hold non-dict entries; reason must stay empty."""
    err = map_http_error(403, '{"error": {"errors": ["forbidden"]}}')
    assert err.code == "FORBIDDEN"


def test_map_http_error_403_plain_text_no_json() -> None:
    err = map_http_error(403, "<html>Forbidden</html>")
    assert err.code == "FORBIDDEN"


def test_map_http_error_404() -> None:
    err = map_http_error(404, '{"error": {"errors": [{"reason": "notFound"}]}}')
    assert err.code == "NOT_FOUND"
    assert err.status_code == 404
    assert err.retryable is False


def test_map_http_error_429_is_retryable() -> None:
    err = map_http_error(429, "too many requests")
    assert err.code == "RATE_LIMIT"
    assert err.status_code == 429
    assert err.retryable is True


def test_map_http_error_401() -> None:
    err = map_http_error(401, "Unauthorized")
    assert err.code == "AUTH_REQUIRED"
    assert err.status_code == 401
    assert err.retryable is False


def test_map_http_error_503_is_server_error() -> None:
    err = map_http_error(503, "backend down")
    assert err.code == "SERVER_ERROR"
    assert err.status_code == 503
    assert err.retryable is True


def test_map_http_error_other_status_truncates_body() -> None:
    err = map_http_error(400, "x" * 300)
    assert err.code == "HTTP_ERROR"
    assert err.status_code == 400
    assert err.retryable is False
    assert err.message == "HTTP 400: " + "x" * 200


# ---------------------------------------------------------------------------
# Successful verbs
# ---------------------------------------------------------------------------


@respx.mock
def test_get_success() -> None:
    route = respx.get(f"{BASE}/videos").mock(
        return_value=httpx.Response(200, json={"items": [{"id": "abc"}]})
    )
    with _make_client() as client:
        out = client.get("videos", params={"id": "abc"})
    assert out == {"items": [{"id": "abc"}]}
    assert route.calls.last.request.method == "GET"
    assert route.calls.last.request.url.params["id"] == "abc"


@respx.mock
def test_post_success_sends_json_body_and_bearer_token() -> None:
    route = respx.post(f"{BASE}/videos").mock(return_value=httpx.Response(200, json={"id": "new"}))
    with _make_client() as client:
        out = client.post("videos", json_body={"snippet": {"title": "t"}})
    assert out == {"id": "new"}
    request = route.calls.last.request
    assert request.method == "POST"
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert request.headers["Accept"] == "application/json"
    assert request.content == b'{"snippet":{"title":"t"}}'


@respx.mock
def test_put_success() -> None:
    route = respx.put(f"{BASE}/videos").mock(return_value=httpx.Response(200, json={"ok": 1}))
    with _make_client() as client:
        assert client.put("videos", json_body={"id": "x"}) == {"ok": 1}
    assert route.calls.last.request.method == "PUT"


@respx.mock
def test_delete_204_returns_empty_dict() -> None:
    route = respx.delete(f"{BASE}/videos/x").mock(return_value=httpx.Response(204))
    with _make_client() as client:
        assert client.delete("videos/x") == {}
    assert route.calls.last.request.method == "DELETE"


@respx.mock
def test_200_with_empty_body_returns_empty_dict() -> None:
    respx.get(f"{BASE}/ping").mock(return_value=httpx.Response(200, content=b""))
    with _make_client() as client:
        assert client.get("ping") == {}


@respx.mock
def test_absolute_url_bypasses_base_url() -> None:
    route = respx.get("https://other.test/raw").mock(
        return_value=httpx.Response(200, json={"z": 1})
    )
    with _make_client() as client:
        assert client.get("https://other.test/raw") == {"z": 1}
    assert str(route.calls.last.request.url) == "https://other.test/raw"


@respx.mock
def test_path_with_leading_slash_is_normalised() -> None:
    route = respx.get(f"{BASE}/videos").mock(return_value=httpx.Response(200, json={}))
    with _make_client() as client:
        client.get("/videos")
    assert str(route.calls.last.request.url) == f"{BASE}/videos"


# ---------------------------------------------------------------------------
# Mapped HTTP errors through request()
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "body", "code", "retryable", "attempts"),
    [
        (401, "Unauthorized", "AUTH_REQUIRED", False, 1),
        (403, '{"error": {"errors": [{"reason": "quotaExceeded"}]}}', "QUOTA_EXCEEDED", False, 1),
        (403, "plain forbidden", "FORBIDDEN", False, 1),
        (404, "missing", "NOT_FOUND", False, 1),
        (429, "slow down", "RATE_LIMIT", True, 1),
        (500, "boom", "SERVER_ERROR", True, 2),
    ],
)
@respx.mock
def test_request_maps_http_status(
    status: int, body: str, code: str, retryable: bool, attempts: int
) -> None:
    """Ошибки поднимаются на первой попытке, кроме тех, что клиент ретраит сам.

    Флаг ``retryable`` описывает, советует ли сервер повторить запрос; клиент
    повторяет его не всегда: 429 помечен как retryable, но автоматически НЕ
    повторяется — правила проекта требуют остановиться на первом 429.
    """
    route = respx.get(f"{BASE}/videos").mock(return_value=httpx.Response(status, text=body))
    client = _make_client(max_retries=1)
    with pytest.raises(ClientError) as ei:
        client.get("videos")
    err = ei.value
    assert err.code == code
    assert err.status_code == status
    assert err.retryable is retryable
    assert len(route.calls) == attempts


# ---------------------------------------------------------------------------
# Retries
# ---------------------------------------------------------------------------


@respx.mock
def test_retryable_500_recovers_on_second_attempt(sleep_calls: list[float]) -> None:
    route = respx.post(f"{BASE}/videos").mock(
        side_effect=[
            httpx.Response(500, text="first boom"),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    with _make_client(max_retries=3) as client:
        out = client.post("videos", json_body={"a": 1})
    assert out == {"ok": True}
    assert len(route.calls) == 2
    assert sleep_calls == [0.5]  # 0.5 * 2**0


@respx.mock
def test_attempt_count_matches_max_retries(sleep_calls: list[float]) -> None:
    route = respx.get(f"{BASE}/videos").mock(return_value=httpx.Response(500, text="boom"))
    client = _make_client(max_retries=2)
    with pytest.raises(ClientError) as ei:
        client.get("videos")
    assert ei.value.code == "SERVER_ERROR"
    assert len(route.calls) == 3  # initial + 2 retries
    assert sleep_calls == [0.5, 1.0]


@respx.mock
def test_max_retries_zero_makes_single_attempt(sleep_calls: list[float]) -> None:
    route = respx.get(f"{BASE}/videos").mock(return_value=httpx.Response(429, text="slow"))
    client = _make_client(max_retries=0)
    with pytest.raises(ClientError) as ei:
        client.get("videos")
    assert ei.value.code == "RATE_LIMIT"
    assert len(route.calls) == 1
    assert sleep_calls == []


@respx.mock
def test_non_retryable_error_is_not_retried(sleep_calls: list[float]) -> None:
    route = respx.get(f"{BASE}/videos").mock(return_value=httpx.Response(404, text="gone"))
    client = _make_client(max_retries=5)
    with pytest.raises(ClientError) as ei:
        client.get("videos")
    assert ei.value.code == "NOT_FOUND"
    assert len(route.calls) == 1
    assert sleep_calls == []


@respx.mock
def test_retry_after_header_drives_backoff(sleep_calls: list[float]) -> None:
    route = respx.get(f"{BASE}/videos").mock(
        side_effect=[
            httpx.Response(503, text="slow", headers={"Retry-After": "3"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    with _make_client(max_retries=1) as client:
        assert client.get("videos") == {"ok": True}
    assert len(route.calls) == 2
    assert sleep_calls == [3.0]


@respx.mock
def test_retry_after_exposed_on_raised_error() -> None:
    respx.get(f"{BASE}/videos").mock(
        return_value=httpx.Response(429, text="slow", headers={"Retry-After": "7"})
    )
    client = _make_client(max_retries=0)
    with pytest.raises(ClientError) as ei:
        client.get("videos")
    assert ei.value.code == "RATE_LIMIT"
    assert ei.value.retry_after == 7.0


@respx.mock
def test_retry_after_http_date_falls_back_to_backoff(sleep_calls: list[float]) -> None:
    """A date-formatted Retry-After cannot be a float; use exponential backoff."""
    route = respx.get(f"{BASE}/videos").mock(
        side_effect=[
            httpx.Response(
                503,
                text="slow",
                headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"},
            ),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    with _make_client(max_retries=1) as client:
        assert client.get("videos") == {"ok": True}
    assert len(route.calls) == 2
    assert sleep_calls == [0.5]  # 0.5 * 2**0, not the unparsable header


@respx.mock
def test_retry_after_is_clamped_to_sixty_seconds(sleep_calls: list[float]) -> None:
    respx.get(f"{BASE}/videos").mock(
        side_effect=[
            httpx.Response(503, text="slow", headers={"Retry-After": "9999"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    with _make_client(max_retries=1) as client:
        assert client.get("videos") == {"ok": True}
    assert sleep_calls == [60.0]


# ---------------------------------------------------------------------------
# Transport errors
# ---------------------------------------------------------------------------


@respx.mock
def test_connect_error_becomes_network_error(sleep_calls: list[float]) -> None:
    route = respx.get(f"{BASE}/videos").mock(side_effect=httpx.ConnectError("refused"))
    client = _make_client(max_retries=1)
    with pytest.raises(ClientError) as ei:
        client.get("videos")
    err = ei.value
    assert err.code == "NETWORK_ERROR"
    assert err.retryable is True
    assert isinstance(err.__cause__, httpx.ConnectError)
    assert len(route.calls) == 2
    assert sleep_calls == [0.5]


@respx.mock
def test_timeout_exception_becomes_network_error(sleep_calls: list[float]) -> None:
    route = respx.get(f"{BASE}/videos").mock(side_effect=httpx.TimeoutException("timed out"))
    client = _make_client(max_retries=2)
    with pytest.raises(ClientError) as ei:
        client.get("videos")
    assert ei.value.code == "NETWORK_ERROR"
    assert ei.value.retryable is True
    assert len(route.calls) == 3
    assert sleep_calls == [0.5, 1.0]


@respx.mock
def test_transport_error_recovers_on_retry(sleep_calls: list[float]) -> None:
    route = respx.get(f"{BASE}/videos").mock(
        side_effect=[
            httpx.ConnectError("blip"),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    with _make_client(max_retries=2) as client:
        assert client.get("videos") == {"ok": True}
    assert len(route.calls) == 2
    assert sleep_calls == [0.5]


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


def test_circuit_closed_initially() -> None:
    client = _make_client()
    assert client.circuit_closed is True
    assert client._failures == 0
    client.close()


@respx.mock
def test_circuit_opens_after_threshold_and_blocks_requests() -> None:
    route = respx.get(f"{BASE}/videos").mock(return_value=httpx.Response(500, text="boom"))
    client = _make_client(max_retries=0, failure_threshold=2)

    with pytest.raises(ClientError) as first:
        client.get("videos")
    assert first.value.code == "SERVER_ERROR"
    assert client.circuit_closed is True  # 1 failure, below threshold

    with pytest.raises(ClientError):
        client.get("videos")
    assert client.circuit_closed is False  # threshold reached

    with pytest.raises(CircuitOpenError) as blocked:
        client.get("videos")
    assert blocked.value.code == "CIRCUIT_OPEN"
    assert blocked.value.retryable is True
    # The blocked call never reached the transport.
    assert len(route.calls) == 2
    client.close()


def test_record_success_closes_circuit() -> None:
    client = _make_client(failure_threshold=1)
    client._record_failure()
    assert client.circuit_closed is False
    client._record_success()
    assert client.circuit_closed is True
    assert client._failures == 0
    client.close()


def test_circuit_reopens_after_recovery_timeout() -> None:
    client = _make_client(failure_threshold=1, recovery_timeout=60.0)
    client._record_failure()
    assert client.circuit_closed is False

    client._opened_at = time.time() - 61.0  # timeout elapsed
    assert client.circuit_closed is True
    assert client._failures == 0
    assert client._opened_at is None
    client.close()


@respx.mock
def test_recovered_circuit_allows_request_again() -> None:
    route = respx.get(f"{BASE}/videos").mock(
        side_effect=[
            httpx.Response(500, text="boom"),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    client = _make_client(max_retries=0, failure_threshold=1, recovery_timeout=60.0)
    with pytest.raises(ClientError):
        client.get("videos")
    assert client.circuit_closed is False

    client._opened_at = time.time() - 61.0
    assert client.circuit_closed is True
    assert client.get("videos") == {"ok": True}
    assert len(route.calls) == 2
    client.close()


# ---------------------------------------------------------------------------
# dry_run, auth and transport configuration
# ---------------------------------------------------------------------------


@respx.mock
def test_dry_run_makes_no_http_call_and_needs_no_token() -> None:
    route = respx.post(f"{BASE}/videos").mock(return_value=httpx.Response(200, json={"ok": True}))
    client = HttpClient(base_url=BASE, access_token=None)
    out = client.post("videos", json_body={"a": 1}, dry_run=True)
    assert out["dry_run"] is True
    assert out["method"] == "POST"
    assert out["url"] == f"{BASE}/videos"
    assert out["params"] is None
    assert route.called is False
    client.close()


@respx.mock
def test_dry_run_get_makes_no_http_call() -> None:
    route = respx.get(f"{BASE}/videos").mock(return_value=httpx.Response(200, json={}))
    client = HttpClient(base_url=BASE, access_token="")
    assert client.get("videos", dry_run=True)["dry_run"] is True
    assert route.called is False
    client.close()


@pytest.mark.parametrize("token", ["", None])
@respx.mock
def test_missing_token_fails_before_network(token: str | None) -> None:
    route = respx.get(f"{BASE}/videos").mock(return_value=httpx.Response(200, json={}))
    client = HttpClient(base_url=BASE, access_token=token)
    with pytest.raises(ClientError) as ei:
        client.get("videos")
    assert ei.value.code == "NOT_AUTHENTICATED"
    assert ei.value.retryable is False
    assert route.called is False
    client.close()


def test_headers_omit_authorization_without_token() -> None:
    client = HttpClient(base_url=BASE, access_token=None)
    assert client._headers() == {"Accept": "application/json"}
    client.close()


def test_http_client_is_configured_with_trust_env_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class _CapturingClient:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

        def close(self) -> None: ...

    monkeypatch.setattr(client_mod.httpx, "Client", _CapturingClient)

    client = HttpClient(base_url=BASE, access_token=TOKEN, timeout=7.5)

    assert captured["trust_env"] is False
    assert captured["timeout"] == 7.5
    client.close()


@respx.mock
def test_context_manager_closes_client() -> None:
    route = respx.get(f"{BASE}/videos").mock(return_value=httpx.Response(200, json={}))
    client = _make_client()
    transport = client._client
    with client as entered:
        assert entered is client
        assert entered.get("videos") == {}
    assert route.called is True
    assert transport.is_closed is True


def test_rate_limit_is_not_auto_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """429 не повторяется автоматически: правила проекта требуют стоп на первом 429.

    Ретраи пачками по лимиту — прямой путь к бану; AGENTS.md: «Стоп на первом
    403/429. Не ретраить пачками».
    """
    monkeypatch.setattr(client_mod.time, "sleep", lambda _s: None)

    with respx.mock:
        route = respx.get(f"{BASE}/videos").mock(
            return_value=httpx.Response(429, text="rate limit", headers={"Retry-After": "1"})
        )
        client = HttpClient(base_url=BASE, access_token=TOKEN, max_retries=3)

        with pytest.raises(ClientError) as ei:
            client.get("videos")

    assert ei.value.code == "RATE_LIMIT"
    assert len(route.calls) == 1, "клиент не должен повторять запрос при 429"
