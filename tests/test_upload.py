"""Upload dry-run tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from aiyoutubehands.upload import prepare_upload, execute_upload_dry_run, UploadError


def test_prepare_and_dry_run(tmp_path: Path) -> None:
    f = tmp_path / "vid.bin"
    f.write_bytes(b"fake video content")
    plan = prepare_upload(f, title="Test", dry_run=True)
    assert plan.size == len(b"fake video content")
    assert plan.sha256
    result = execute_upload_dry_run(plan)
    assert result["dry_run"] is True
    assert result["video_id"] is None


def test_dry_run_helper_always_safe(tmp_path: Path) -> None:
    f = tmp_path / "v.bin"
    f.write_bytes(b"x")
    plan = prepare_upload(f, title="T", dry_run=False)
    result = execute_upload_dry_run(plan)
    assert result["dry_run"] is True
    assert result["video_id"] is None


def test_missing_file() -> None:
    with pytest.raises(UploadError) as ei:
        prepare_upload("/nonexistent/file.mp4", title="x")
    assert ei.value.code == "FILE_NOT_FOUND"


def test_resumable_requires_yes(tmp_path: Path) -> None:
    f = tmp_path / "v.bin"
    f.write_bytes(b"data")
    plan = prepare_upload(f, title="T", dry_run=False)
    from aiyoutubehands.upload import execute_resumable_upload
    with pytest.raises(UploadError) as ei:
        execute_resumable_upload(plan, access_token="x", yes=False)
    assert ei.value.code == "CONFIRM_REQUIRED"


def test_resumable_requires_token(tmp_path: Path, monkeypatch) -> None:
    """Пустой токен отвергается до сети, а не даёт `Bearer ` и 401 в сессии.

    Регресс: `assert client.access_token` в upload_cmd исчезает под `python -O`.
    """
    from aiyoutubehands import upload as upload_mod
    from aiyoutubehands.upload import execute_resumable_upload

    calls: list[str] = []

    class _FakeResp401:
        status_code = 401
        text = "Unauthorized"
        headers: dict = {}

    class _FakeHTTP:
        def __init__(self, *a, **k): ...

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            calls.append("post")
            return _FakeResp401()

    monkeypatch.setattr(upload_mod.httpx, "Client", _FakeHTTP)

    f = tmp_path / "v.bin"
    f.write_bytes(b"data")
    plan = prepare_upload(f, title="T", dry_run=False)

    with pytest.raises(UploadError) as ei:
        execute_resumable_upload(plan, access_token="", yes=True)

    assert ei.value.code == "NOT_AUTHENTICATED"
    assert calls == []
