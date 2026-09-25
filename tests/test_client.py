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
