"""Tests for YoutubeService (dry-run only)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from aiyoutubehands.client import HttpClient
from aiyoutubehands.models.youtube import VideoSnippet
from aiyoutubehands.quota import QuotaEngine
from aiyoutubehands.youtube import COST, YoutubeService

if TYPE_CHECKING:
    from pathlib import Path


def test_get_my_channel_dry_run(tmp_path: Path) -> None:
    client = HttpClient(access_token="fake")
    quota = QuotaEngine(db_path=tmp_path / "q.db")
    yt = YoutubeService(client, quota, expected_channel_id="UC_test")
    result = yt.get_my_channel(dry_run=True)
    assert isinstance(result, dict)
    assert result["dry_run"] is True


def test_get_video_dry_run(tmp_path: Path) -> None:
    client = HttpClient()
    quota = QuotaEngine(db_path=tmp_path / "q.db")
    yt = YoutubeService(client, quota, expected_channel_id="UC_test")
    result = yt.get_video("abc", dry_run=True)
    assert result["dry_run"] is True


def test_cost_table() -> None:
    assert COST["videos.insert"] == 1600
    assert COST["search.list"] == 100


def test_claims_unsupported(tmp_path: Path) -> None:
    client = HttpClient()
    quota = QuotaEngine(db_path=tmp_path / "q.db")
    yt = YoutubeService(client, quota, expected_channel_id="UC_test")
    r = yt.claims_unsupported()
    assert r["status"] == "UNSUPPORTED"


def test_update_requires_yes(tmp_path: Path) -> None:
    from aiyoutubehands.client import ClientError
    from aiyoutubehands.models.youtube import VideoSnippet

    client = HttpClient()
    quota = QuotaEngine(db_path=tmp_path / "q.db")
    yt = YoutubeService(client, quota, expected_channel_id="UC_test")
    try:
        yt.update_video("v", snippet=VideoSnippet(title="t"), dry_run=False, yes=False)
        raise AssertionError("expected ClientError")
    except ClientError as e:
        assert e.code == "CONFIRM_REQUIRED"


def test_schedule_and_playlist_dry_run(tmp_path: Path) -> None:
    client = HttpClient()
    quota = QuotaEngine(db_path=tmp_path / "q.db")
    yt = YoutubeService(client, quota, expected_channel_id="UC_test")
    r = yt.schedule_video("vid", "2026-10-01T12:00:00Z", dry_run=True, yes=True)
    assert r["dry_run"] is True
    r2 = yt.create_playlist("T", dry_run=True, yes=True)
    assert r2["dry_run"] is True
    r3 = yt.moderate_comment("c1", "published", dry_run=True, yes=True)
    assert r3.get("dry_run") is True or "dry_run" in r3


def test_list_channel_videos_dry_run(tmp_path: Path) -> None:
    client = HttpClient(access_token="fake")
    quota = QuotaEngine(db_path=tmp_path / "q.db")
    yt = YoutubeService(client, quota, expected_channel_id="UC_test")
    result = yt.list_channel_videos(max_age_days=14, dry_run=True)
    assert isinstance(result, dict)
    assert result["dry_run"] is True
    assert result["method"] == "list_channel_videos"


def test_list_video_ids_in_playlists_dry_run(tmp_path: Path) -> None:
    client = HttpClient(access_token="fake")
    quota = QuotaEngine(db_path=tmp_path / "q.db")
    yt = YoutubeService(client, quota, expected_channel_id="UC_test")
    result = yt.list_video_ids_in_playlists(dry_run=True)
    assert isinstance(result, dict)
    assert result["dry_run"] is True


def test_set_thumbnail_requires_token(tmp_path: Path, monkeypatch) -> None:
    """Пустой токен отвергается до сети.

    set_thumbnail шлёт запрос своим httpx.Client в обход HttpClient, поэтому
    общий страж в HttpClient его не покрывает.
    """
    import aiyoutubehands.youtube as yt_mod
    from aiyoutubehands.client import ClientError

    calls: list[str] = []

    class _FakeResp401:
        status_code = 401
        text = "Unauthorized"
        headers: dict = {}
        content = b"{}"

        def json(self) -> dict:
            return {}

    class _FakeHTTP:
        def __init__(self, *a, **k): ...

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            calls.append("post")
            return _FakeResp401()

    client = HttpClient(access_token="fake")
    quota = QuotaEngine(db_path=tmp_path / "q.db")
    yt = YoutubeService(client, quota, expected_channel_id="UC_test")

    monkeypatch.setattr(yt_mod.httpx, "Client", _FakeHTTP)

    image = tmp_path / "cover.jpg"
    image.write_bytes(b"\xff\xd8\xff")

    with pytest.raises(ClientError) as ei:
        yt.set_thumbnail("vid1", image, access_token="", dry_run=False, yes=True)

    assert ei.value.code == "NOT_AUTHENTICATED"
    assert calls == []


class _Resp:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.status_code = 200
        self.text = ""
        self.headers: dict = {}
        self.content = b"{}"

    def json(self) -> dict:
        return self._payload


def _patch_http(monkeypatch, payload: dict) -> list[str]:
    """Подменить httpx.Client так, чтобы channels.list вернул payload."""
    import aiyoutubehands.client as client_mod

    calls: list[str] = []

    class _FakeHTTP:
        def __init__(self, *a, **k): ...

        def request(self, method, url, **kwargs):
            calls.append(f"{method} {url}")
            return _Resp(payload)

        def close(self): ...

    monkeypatch.setattr(client_mod.httpx, "Client", _FakeHTTP)
    return calls


def test_write_refuses_on_channel_mismatch(tmp_path: Path, monkeypatch) -> None:
    """Мутация не должна выполняться, если токен принадлежит другому каналу.

    Регресс: _guard_channel вызывался только в get_my_channel(), поэтому ни один
    write-метод канал не проверял. Аккаунт с несколькими каналами мог записать
    метаданные не туда, а exit-код CHANNEL_MISMATCH (71) был недостижим.
    """
    from aiyoutubehands.client import ClientError

    _patch_http(monkeypatch, {"items": [{"id": "UC_OTHER", "snippet": {"title": "Другой"}}]})
    client = HttpClient(access_token="fake")
    quota = QuotaEngine(db_path=tmp_path / "q.db")
    yt = YoutubeService(client, quota, expected_channel_id="UC_EXPECTED")

    with pytest.raises(ClientError) as ei:
        yt.update_video("v", snippet=VideoSnippet(title="t"), dry_run=False, yes=True)

    assert ei.value.code == "CHANNEL_MISMATCH"


def test_write_refuses_without_expected_channel_id(tmp_path: Path, monkeypatch) -> None:
    """Пустой expected_channel_id — это отказ, а не «проверка не нужна».

    Регресс: _guard_channel молча пропускал проверку при пустом ожидаемом
    значении (fail-open).
    """
    from aiyoutubehands.client import ClientError

    _patch_http(monkeypatch, {"items": [{"id": "UC_ANY", "snippet": {"title": "Любой"}}]})
    client = HttpClient(access_token="fake")
    quota = QuotaEngine(db_path=tmp_path / "q.db")
    yt = YoutubeService(client, quota, expected_channel_id="")

    with pytest.raises(ClientError) as ei:
        yt.update_video("v", snippet=VideoSnippet(title="t"), dry_run=False, yes=True)

    assert ei.value.code == "CHANNEL_NOT_CONFIGURED"


def test_write_dry_run_makes_no_network_calls(tmp_path: Path, monkeypatch) -> None:
    """dry-run не должен ходить в сеть, в том числе за проверкой канала."""
    calls = _patch_http(monkeypatch, {"items": [{"id": "UC_OTHER", "snippet": {}}]})
    client = HttpClient(access_token="fake")
    quota = QuotaEngine(db_path=tmp_path / "q.db")
    yt = YoutubeService(client, quota, expected_channel_id="UC_EXPECTED")

    result = yt.update_video("v", snippet=VideoSnippet(title="t"), dry_run=True)

    assert result["dry_run"] is True
    assert calls == []


def test_list_playlists_follows_pagination(tmp_path: Path, monkeypatch) -> None:
    """Канал с >50 плейлистами не должен молча обрезаться.

    Регресс: list_playlists делал один запрос с maxResults=50 и не читал
    nextPageToken, поэтому сигнал «уже оформлено» терялся на больших каналах,
    и уже оформленные видео попадали в план повторно.
    """
    import aiyoutubehands.client as client_mod

    pages = [
        {
            "items": [
                {"id": "PL1", "snippet": {"title": "A"}, "contentDetails": {"itemCount": "1"}}
            ],
            "nextPageToken": "T2",
        },
        {"items": [{"id": "PL2", "snippet": {"title": "B"}, "contentDetails": {"itemCount": "2"}}]},
    ]
    seen_params: list[dict] = []

    class _Page:
        def __init__(self, payload: dict) -> None:
            self._payload = payload
            self.status_code = 200
            self.text = ""
            self.headers: dict = {}
            self.content = b"{}"

        def json(self) -> dict:
            return self._payload

    class _FakeHTTP:
        def __init__(self, *a, **k): ...

        def request(self, method, url, **kwargs):
            params = dict(kwargs.get("params") or {})
            seen_params.append(params)
            return _Page(pages[1] if params.get("pageToken") == "T2" else pages[0])

        def close(self): ...

    monkeypatch.setattr(client_mod.httpx, "Client", _FakeHTTP)

    client = HttpClient(access_token="fake")
    quota = QuotaEngine(db_path=tmp_path / "q.db")
    yt = YoutubeService(client, quota, expected_channel_id="UC_test")

    playlists = yt.list_playlists(dry_run=False)

    assert [p.id for p in playlists] == ["PL1", "PL2"]
    assert len(seen_params) == 2
    assert seen_params[1]["pageToken"] == "T2"
