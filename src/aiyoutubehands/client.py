"""HTTP client with retries, circuit breaker and error mapping."""

from __future__ import annotations

import time
from typing import Any

import httpx

from aiyoutubehands.logging import get_logger

log = get_logger(__name__)

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"


class ClientError(Exception):
    """Mapped HTTP / API error."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "CLIENT_ERROR",
        status_code: int | None = None,
        action: str = "Повторите позже или проверьте запрос",
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.action = action
        self.retryable = retryable


class CircuitOpenError(ClientError):
    def __init__(self) -> None:
        super().__init__(
            "Circuit breaker открыт — слишком много ошибок",
            code="CIRCUIT_OPEN",
            action="Подождите и повторите",
            retryable=True,
        )


def map_http_error(status: int, body: str = "") -> ClientError:
    body_l = body.lower()
    if status == 401:
        return ClientError(
            "Требуется авторизация",
            code="AUTH_REQUIRED",
            status_code=401,
            action="Выполните ayh auth login",
            retryable=False,
        )
    if status == 403:
        if "quota" in body_l or "quotaexceeded" in body_l:
            return ClientError(
                "Квота YouTube API исчерпана",
                code="QUOTA_EXCEEDED",
                status_code=403,
                action="Дождитесь сброса квоты",
                retryable=False,
            )
        return ClientError(
            "Доступ запрещён",
            code="FORBIDDEN",
            status_code=403,
            action="Проверьте scopes и channel_id",
            retryable=False,
        )
    if status == 404:
        return ClientError(
            "Ресурс не найден",
            code="NOT_FOUND",
            status_code=404,
            action="Проверьте ID",
            retryable=False,
        )
    if status == 429:
        return ClientError(
            "Rate limit",
            code="RATE_LIMIT",
            status_code=429,
            action="Повторите позже",
            retryable=True,
        )
    if status >= 500:
        return ClientError(
            f"Ошибка сервера YouTube ({status})",
            code="SERVER_ERROR",
            status_code=status,
            action="Повторите позже",
            retryable=True,
        )
    return ClientError(
        f"HTTP {status}: {body[:200]}",
        code="HTTP_ERROR",
        status_code=status,
        retryable=False,
    )


class HttpClient:
    """httpx-based client with retries and circuit breaker."""

    def __init__(
        self,
        base_url: str = YOUTUBE_API_BASE,
        access_token: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.access_token = access_token
        self.timeout = timeout
        self.max_retries = max_retries
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._failures = 0
        self._opened_at: float | None = None
        self._client = httpx.Client(timeout=timeout)

    @property
    def circuit_closed(self) -> bool:
        if self._opened_at is None:
            return True
        if time.time() - self._opened_at >= self.recovery_timeout:
            self._opened_at = None
            self._failures = 0
            return True
        return False

    def _ensure_circuit(self) -> None:
        if not self.circuit_closed:
            raise CircuitOpenError()

    def _record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._opened_at = time.time()
            log.warning("circuit_opened", failures=self._failures)

    def _record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def _headers(self) -> dict[str, str]:
        h = {"Accept": "application/json"}
        if self.access_token:
            h["Authorization"] = f"Bearer {self.access_token}"
        return h

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        self._ensure_circuit()
        url = path if path.startswith("http") else f"{self.base_url}/{path.lstrip('/')}"

        if dry_run:
            log.info("http_dry_run", method=method, url=url, params=params)
            return {"dry_run": True, "method": method, "url": url, "params": params}

        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._client.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers=self._headers(),
                )
                if resp.status_code >= 400:
                    err = map_http_error(resp.status_code, resp.text)
                    if err.retryable and attempt < self.max_retries:
                        time.sleep(0.5 * (2**attempt))
                        last_exc = err
                        continue
                    self._record_failure()
                    raise err
                self._record_success()
                if resp.status_code == 204 or not resp.content:
                    return {}
                return resp.json()  # type: ignore[no-any-return]
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                self._record_failure()
                if attempt < self.max_retries:
                    time.sleep(0.5 * (2**attempt))
                    continue
                raise ClientError(
                    f"Сетевая ошибка: {exc}",
                    code="NETWORK_ERROR",
                    action="Проверьте интернет",
                    retryable=True,
                ) from exc
        if last_exc:
            raise last_exc
        raise ClientError("Неизвестная ошибка запроса", code="UNKNOWN")

    def get(self, path: str, **kwargs: Any) -> dict[str, Any]:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> dict[str, Any]:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> dict[str, Any]:
        return self.request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> dict[str, Any]:
        return self.request("DELETE", path, **kwargs)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
