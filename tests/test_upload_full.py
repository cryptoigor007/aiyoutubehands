"""Полное покрытие ``aiyoutubehands.upload``, в т.ч. resumable-загрузка.

Сеть не трогается: ``upload.httpx.Client`` подменяется фейком, который
записывает запросы (url, headers, content/params/json) и отдаёт заранее
заданные ответы.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pytest

from aiyoutubehands import upload as upload_mod
from aiyoutubehands.upload import (
    COST_INSERT,
    UPLOAD_URL,
    UploadError,
    UploadPlan,
    execute_resumable_upload,
    execute_upload_dry_run,
    prepare_upload,
)

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch


class _Resp:
    """Минимальный ответ httpx, которого достаточно upload.py."""

    def __init__(
        self,
        status_code: int,
        *,
        headers: dict[str, str] | None = None,
        json_data: Any = None,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self.headers = headers if headers is not None else {}
        self._json_data = json_data
        self.text = text

    def json(self) -> Any:
        return self._json_data


class _FakeQuota:
    def __init__(self) -> None:
        self.checks: list[int] = []
        self.consumed: list[tuple[str, int]] = []

    def check(self, units: int) -> None:
        self.checks.append(units)

    def consume(self, operation: str, units: int) -> None:
        self.consumed.append((operation, units))


def _make_client_class(
    post_responses: list[_Resp],
    put_responses: list[_Resp],
    calls: list[dict[str, Any]],
) -> type:
    class _Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._post = list(post_responses)
            self._put = list(put_responses)

        def __enter__(self) -> _Client:
            return self

        def __exit__(self, *exc: Any) -> bool:
            return False

        def post(
            self,
            url: str,
            *,
            params: dict[str, str] | None = None,
            headers: dict[str, str] | None = None,
            json: Any = None,
        ) -> _Resp:
            calls.append(
                {"method": "post", "url": url, "params": params, "headers": headers, "json": json}
            )
            return self._post.pop(0)

        def put(
            self,
            url: str,
            *,
            headers: dict[str, str] | None = None,
            content: bytes | None = None,
        ) -> _Resp:
            calls.append({"method": "put", "url": url, "headers": headers, "content": content})
            return self._put.pop(0)

    return _Client


def _patch(
    monkeypatch: MonkeyPatch,
    post_responses: list[_Resp],
    put_responses: list[_Resp] | None = None,
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        upload_mod.httpx,
        "Client",
        _make_client_class(post_responses, put_responses or [], calls),
    )
    return calls


def _make_plan(tmp_path: Path, content: bytes, **kwargs: Any) -> UploadPlan:
    f = tmp_path / "vid.bin"
    f.write_bytes(content)
    kwargs.setdefault("dry_run", False)
    return prepare_upload(f, title="T", **kwargs)


# --- prepare_upload ---------------------------------------------------------


def test_prepare_upload_on_directory_raises(tmp_path: Path) -> None:
    with pytest.raises(UploadError) as ei:
        prepare_upload(tmp_path, title="T")
    assert ei.value.code == "FILE_NOT_FOUND"


# --- execute_upload_dry_run / short-circuits --------------------------------


def test_execute_resumable_dry_run_short_circuits(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    plan = _make_plan(tmp_path, b"data", dry_run=True)
    calls = _patch(monkeypatch, [])
    result = execute_resumable_upload(plan, access_token="tok", yes=True)
    assert result["dry_run"] is True
    assert result["video_id"] is None
    assert calls == []


def test_execute_resumable_requires_yes(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    plan = _make_plan(tmp_path, b"data")
    calls = _patch(monkeypatch, [])
    with pytest.raises(UploadError) as ei:
        execute_resumable_upload(plan, access_token="tok", yes=False)
    assert ei.value.code == "CONFIRM_REQUIRED"
    assert calls == []


def test_execute_resumable_requires_token(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    plan = _make_plan(tmp_path, b"data")
    calls = _patch(monkeypatch, [])
    with pytest.raises(UploadError) as ei:
        execute_resumable_upload(plan, access_token="", yes=True)
    assert ei.value.code == "NOT_AUTHENTICATED"
    assert calls == []


# --- init failures ----------------------------------------------------------


def test_init_status_failure_raises_init_failed(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    plan = _make_plan(tmp_path, b"data")
    _patch(monkeypatch, [_Resp(500, text="boom")])
    with pytest.raises(UploadError) as ei:
        execute_resumable_upload(plan, access_token="tok", yes=True)
    assert ei.value.code == "UPLOAD_INIT_FAILED"
    assert ei.value.retryable is True


def test_init_without_location_raises_no_session(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    plan = _make_plan(tmp_path, b"data")
    _patch(monkeypatch, [_Resp(200, headers={})])
    with pytest.raises(UploadError) as ei:
        execute_resumable_upload(plan, access_token="tok", yes=True)
    assert ei.value.code == "UPLOAD_NO_SESSION"


# --- successful upload ------------------------------------------------------


def test_resumable_success_multichunk_and_quota(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    content = b"0123456789"
    plan = _make_plan(tmp_path, content)
    quota = _FakeQuota()
    calls = _patch(
        monkeypatch,
        [_Resp(200, headers={"Location": "https://upload.example/session"})],
        [
            _Resp(308),
            _Resp(308),
            _Resp(200, json_data={"id": "vid-123"}),
        ],
    )

    result = execute_resumable_upload(plan, access_token="tok", quota=quota, yes=True, chunk_size=4)

    assert result["ok"] is True
    assert result["dry_run"] is False
    assert result["video_id"] == "vid-123"

    # check — один раз перед сетью, consume — ровно один раз на финале.
    assert quota.checks == [COST_INSERT]
    assert quota.consumed == [("videos.insert", COST_INSERT)]

    post_calls = [c for c in calls if c["method"] == "post"]
    put_calls = [c for c in calls if c["method"] == "put"]
    assert len(post_calls) == 1
    assert len(put_calls) == 3

    init = post_calls[0]
    assert init["url"] == UPLOAD_URL
    assert init["headers"]["Authorization"] == "Bearer tok"
    assert init["headers"]["X-Upload-Content-Length"] == str(len(content))
    assert init["params"]["uploadType"] == "resumable"
    assert init["params"]["notifySubscribers"] == "true"

    ranges = [c["headers"]["Content-Range"] for c in put_calls]
    assert ranges == ["bytes 0-3/10", "bytes 4-7/10", "bytes 8-9/10"]
    assert [c["headers"]["Content-Length"] for c in put_calls] == ["4", "4", "2"]
    assert [c["content"] for c in put_calls] == [b"0123", b"4567", b"89"]
    assert all(c["url"] == "https://upload.example/session" for c in put_calls)


def test_resumable_success_without_quota(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    plan = _make_plan(tmp_path, b"data")
    calls = _patch(
        monkeypatch,
        [_Resp(201, headers={"Location": "https://upload.example/s"})],
        [_Resp(200, json_data={"id": "single"})],
    )
    result = execute_resumable_upload(plan, access_token="tok", yes=True, chunk_size=1024)
    assert result["video_id"] == "single"
    assert len([c for c in calls if c["method"] == "put"]) == 1


def test_resumable_notify_subscribers_false_param(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    plan = _make_plan(tmp_path, b"data", notify_subscribers=False)
    calls = _patch(
        monkeypatch,
        [_Resp(200, headers={"Location": "https://upload.example/s"})],
        [_Resp(200, json_data={"id": "v"})],
    )
    execute_resumable_upload(plan, access_token="tok", yes=True, chunk_size=1024)
    init = calls[0]
    assert init["params"]["notifySubscribers"] == "false"


# --- chunk failures / incomplete -------------------------------------------


def test_chunk_status_failure_raises_chunk_failed(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    plan = _make_plan(tmp_path, b"data")
    _patch(
        monkeypatch,
        [_Resp(200, headers={"Location": "https://upload.example/s"})],
        [_Resp(400, text="bad chunk")],
    )
    with pytest.raises(UploadError) as ei:
        execute_resumable_upload(plan, access_token="tok", yes=True, chunk_size=1024)
    assert ei.value.code == "UPLOAD_CHUNK_FAILED"
    assert ei.value.retryable is True


def test_incomplete_when_file_shorter_than_plan(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    plan = _make_plan(tmp_path, b"data")
    plan = replace(plan, size=100)  # план врёт: файл короче заявленного
    quota = _FakeQuota()
    _patch(
        monkeypatch,
        [_Resp(200, headers={"Location": "https://upload.example/s"})],
        [_Resp(308)],
    )
    with pytest.raises(UploadError) as ei:
        execute_resumable_upload(plan, access_token="tok", quota=quota, yes=True, chunk_size=4)
    assert ei.value.code == "UPLOAD_INCOMPLETE"
    assert quota.consumed == []


def test_incomplete_when_plan_size_zero_and_file_empty(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    plan = _make_plan(tmp_path, b"")
    plan = replace(plan, size=0)
    calls = _patch(monkeypatch, [_Resp(200, headers={"Location": "https://upload.example/s"})])
    with pytest.raises(UploadError) as ei:
        execute_resumable_upload(plan, access_token="tok", yes=True)
    assert ei.value.code == "UPLOAD_INCOMPLETE"
    assert len([c for c in calls if c["method"] == "put"]) == 0


def test_execute_upload_dry_run_shape(tmp_path: Path) -> None:
    f = tmp_path / "v.bin"
    f.write_bytes(b"x")
    plan = prepare_upload(f, title="T", dry_run=False)
    result = execute_upload_dry_run(plan)
    assert result["dry_run"] is True
    assert result["video_id"] is None
    assert result["plan"]["title"] == "T"
