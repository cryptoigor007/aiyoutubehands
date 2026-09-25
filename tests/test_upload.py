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


def test_real_upload_blocked(tmp_path: Path) -> None:
    f = tmp_path / "v.bin"
    f.write_bytes(b"x")
    plan = prepare_upload(f, title="T", dry_run=False)
    with pytest.raises(UploadError) as ei:
        execute_upload_dry_run(plan)
    assert ei.value.code == "UPLOAD_FORBIDDEN"


def test_missing_file() -> None:
    with pytest.raises(UploadError) as ei:
        prepare_upload("/nonexistent/file.mp4", title="x")
    assert ei.value.code == "FILE_NOT_FOUND"
