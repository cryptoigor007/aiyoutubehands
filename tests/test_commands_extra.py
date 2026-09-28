"""CLI-тесты для дополнительных команд (video/playlist/comments/captions/…).

Все реальные (не dry-run) ветки прогоняются через фейковый сервис:
``aiyoutubehands.service_factory.build_youtube_service`` подменяется
``monkeypatch``-ем, поэтому ни один тест не ходит в сеть.

Пароль локального хранилища читается командами интерактивно
(``click.prompt(hide_input=True)``); флаг ``--passphrase`` из CLI удалён.
Поэтому в ``CliRunner`` он передаётся через ``input="secret\n"``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from click.testing import CliRunner, Result

from aiyoutubehands import service_factory
from aiyoutubehands import upload as upload_mod
from aiyoutubehands.client import ClientError
from aiyoutubehands.main import cli
from aiyoutubehands.models.youtube import (
    CaptionResource,
    ChannelResource,
    CommentResource,
    PlaylistResource,
    VideoResource,
    VideoSnippet,
    VideoStatus,
)
from aiyoutubehands.quota import QuotaEngine

if TYPE_CHECKING:
    from pathlib import Path

PASSWORD = "secret\n"
REFUSAL = "Нужен --yes вместе с --no-dry-run"


# --------------------------------------------------------------------------
# Фейковый сервис (без сети)
# --------------------------------------------------------------------------


class FakeClient:
    """Минимальный HttpClient-совместимый двойник."""

    def __init__(self) -> None:
        self.access_token = "fake"
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeYT:
    """YoutubeService-совместимый двойник.

    Каждый метод пишет вызов в ``self.calls`` и возвращает правдоподобный
    ресурс. Флаги ``*_as_dict`` переключают list-методы на «dry-run формат»
    (dict), чтобы покрыть обе ветки CLI-разбора ``isinstance(items, list)``.
    """

    def __init__(self, db_path: Path) -> None:
        self.quota = QuotaEngine(db_path=db_path)
        self.calls: list[tuple[Any, ...]] = []
        self.playlists_as_dict = False
        self.comments_as_dict = False
        self.captions_as_dict = False

    # --- чтение -----------------------------------------------------------
    def get_video(self, video_id: str, *, dry_run: bool = False) -> VideoResource:
        self.calls.append(("get_video", video_id, dry_run))
        if video_id == "bad":
            raise ClientError(f"Видео {video_id} не найдено", code="NOT_FOUND")
        return VideoResource(
            id=video_id,
            snippet=VideoSnippet(title="Test video"),
            status=VideoStatus(privacy_status="private"),
        )

    def list_playlists(self, *, dry_run: bool = False) -> list[PlaylistResource] | dict[str, Any]:
        self.calls.append(("list_playlists", dry_run))
        if self.playlists_as_dict:
            return {"dry_run": True, "items": [{"id": "PL_raw"}]}
        return [
            PlaylistResource(id="PL1", title="List A", item_count=3),
            PlaylistResource(id="PL2", title="List B", item_count=0),
        ]

    def list_comment_threads(
        self, video_id: str, *, dry_run: bool = False
    ) -> list[CommentResource] | dict[str, Any]:
        self.calls.append(("list_comment_threads", video_id, dry_run))
        if self.comments_as_dict:
            return {"dry_run": True, "video_id": video_id}
        return [
            CommentResource(id="c1", author="Alice", text="Nice!"),
            CommentResource(id="c2", author="Bob", text="Thanks"),
        ]

    def list_captions(
        self, video_id: str, *, dry_run: bool = False
    ) -> list[CaptionResource] | dict[str, Any]:
        self.calls.append(("list_captions", video_id, dry_run))
        if self.captions_as_dict:
            return {"dry_run": True, "video_id": video_id}
        return [
            CaptionResource(id="cap1", language="ru", name="Русский"),
            CaptionResource(id="cap2", language="en", name="English"),
        ]

    def get_my_channel(self, *, dry_run: bool = False) -> ChannelResource:
        self.calls.append(("get_my_channel", dry_run))
        return ChannelResource(id="UC_fake", title="My Channel", subscriber_count=42)

    # --- запись -----------------------------------------------------------
    def publish_video(
        self, video_id: str, *, dry_run: bool = False, yes: bool = False
    ) -> dict[str, Any]:
        self.calls.append(("publish_video", video_id, dry_run, yes))
        return {"ok": True}

    def schedule_video(
        self, video_id: str, publish_at: str, *, dry_run: bool = False, yes: bool = False
    ) -> dict[str, Any]:
        self.calls.append(("schedule_video", video_id, publish_at, dry_run, yes))
        return {"ok": True}

    def delete_video(
        self, video_id: str, *, dry_run: bool = False, yes: bool = False
    ) -> dict[str, Any]:
        self.calls.append(("delete_video", video_id, dry_run, yes))
        return {"ok": True}

    def set_thumbnail(
        self,
        video_id: str,
        image_path: str,
        *,
        access_token: str,
        dry_run: bool = False,
        yes: bool = False,
    ) -> dict[str, Any]:
        self.calls.append(("set_thumbnail", video_id, access_token, dry_run, yes))
        return {"ok": True}

    def create_playlist(
        self,
        title: str,
        description: str = "",
        privacy: str = "private",
        *,
        dry_run: bool = False,
        yes: bool = False,
    ) -> PlaylistResource:
        self.calls.append(("create_playlist", title, description, privacy, dry_run, yes))
        return PlaylistResource(id="PLNEW", title=title)

    def add_to_playlist(
        self, playlist_id: str, video_id: str, *, dry_run: bool = False, yes: bool = False
    ) -> dict[str, Any]:
        self.calls.append(("add_to_playlist", playlist_id, video_id, dry_run, yes))
        return {"ok": True}

    def delete_playlist(
        self, playlist_id: str, *, dry_run: bool = False, yes: bool = False
    ) -> dict[str, Any]:
        self.calls.append(("delete_playlist", playlist_id, dry_run, yes))
        return {"ok": True}

    def reply_to_comment(
        self, parent_id: str, text: str, *, dry_run: bool = False, yes: bool = False
    ) -> dict[str, Any]:
        self.calls.append(("reply_to_comment", parent_id, text, dry_run, yes))
        return {"ok": True}

    def moderate_comment(
        self, comment_id: str, moderation_status: str, *, dry_run: bool = False, yes: bool = False
    ) -> dict[str, Any]:
        self.calls.append(("moderate_comment", comment_id, moderation_status, dry_run, yes))
        return {"ok": True}

    def upload_caption(
        self,
        video_id: str,
        file_path: str,
        language: str = "ru",
        name: str = "",
        *,
        access_token: str,
        dry_run: bool = False,
        yes: bool = False,
    ) -> dict[str, Any]:
        self.calls.append(("upload_caption", video_id, language, access_token, dry_run, yes))
        return {"ok": True}


@pytest.fixture
def fake_client() -> FakeClient:
    return FakeClient()


@pytest.fixture
def fake_yt(tmp_path: Path) -> FakeYT:
    return FakeYT(tmp_path / "quota.db")


@pytest.fixture
def patch_service(
    monkeypatch: pytest.MonkeyPatch, fake_yt: FakeYT, fake_client: FakeClient
) -> dict[str, Any]:
    """Подменить build_youtube_service фейком; вернуть словарь-захват аргументов."""
    captured: dict[str, Any] = {}

    def _build(
        *, passphrase: str | None = None, force_quota: bool = False
    ) -> tuple[FakeYT, FakeClient]:
        captured["passphrase"] = passphrase
        captured["force_quota"] = force_quota
        return fake_yt, fake_client

    monkeypatch.setattr(service_factory, "build_youtube_service", _build)
    return captured


@pytest.fixture
def forbid_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Любой выход в сеть в dry-run должен уронить тест."""

    def _boom(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("dry-run не должен обращаться к сети")

    monkeypatch.setattr(service_factory, "build_youtube_service", _boom)
    monkeypatch.setattr(httpx, "Client", _boom)


def _invoke(args: list[str], *, password: bool = False) -> Result:
    runner = CliRunner()
    return runner.invoke(cli, args, input=PASSWORD if password else None)


def _json_from_output(output: str) -> Any:
    """Разобрать JSON, отбросив строку интерактивного приглашения пароля."""
    starts = [i for i in (output.find("{"), output.find("[")) if i != -1]
    assert starts, output
    return json.loads(output[min(starts) :])


# --------------------------------------------------------------------------
# dry-run: сеть запрещена полностью
# --------------------------------------------------------------------------


def test_dry_run_commands_never_touch_network(tmp_path: Path, forbid_network: None) -> None:
    img = tmp_path / "cover.jpg"
    img.write_bytes(b"img")
    srt = tmp_path / "subs.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")
    video_file = tmp_path / "clip.mp4"
    video_file.write_bytes(b"video")

    cases = [
        ["video", "info", "v1"],
        ["video", "info", "v1", "--json"],
        ["video", "publish", "v1"],
        ["video", "schedule", "v1", "2026-10-01T15:00:00Z"],
        ["video", "delete", "v1"],
        ["video", "thumbnail", "v1", str(img)],
        ["playlist", "list"],
        ["playlist", "list", "--json"],
        ["playlist", "create", "New"],
        ["playlist", "add", "PL1", "v1"],
        ["playlist", "delete", "PL1"],
        ["comments", "list", "v1"],
        ["comments", "list", "v1", "--json"],
        ["comments", "reply", "c1", "hi"],
        ["comments", "moderate", "c1", "rejected"],
        ["captions", "list", "v1"],
        ["captions", "list", "v1", "--json"],
        ["captions", "upload", "v1", str(srt)],
        ["channel", "info"],
        ["channel", "info", "--json"],
        ["upload", "prepare", str(video_file), "--title", "T"],
        ["upload", "run", str(video_file), "--title", "T"],
        ["ai", "title", "python"],
        ["ai", "description", "python"],
        ["ai", "tags", "python"],
        ["ai", "script", "python"],
        ["ai", "thumbnail", "python"],
        ["ai", "chapters", "python"],
        ["ai", "translate", "hello", "--lang", "ru"],
        ["ai", "calendar", "it", "--days", "3"],
        ["calendar", "list", "--db", str(tmp_path / "c.db")],
        ["calendar", "grid", "--db", str(tmp_path / "c.db")],
        ["quota", "status", "--db", str(tmp_path / "q.db")],
        ["--log-level", "ERROR", "doctor", "--json"],
    ]
    runner = CliRunner()
    for args in cases:
        result = runner.invoke(cli, args)
        assert result.exit_code == 0, (args, result.output)


# --------------------------------------------------------------------------
# dry-run: точный вывод
# --------------------------------------------------------------------------


def test_video_info_dry_run_plain() -> None:
    result = _invoke(["video", "info", "v1"])
    assert result.exit_code == 0
    assert "v1" in result.output
    assert "dry-run" in result.output


def test_video_info_dry_run_json() -> None:
    result = _invoke(["video", "info", "v1", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == {"dry_run": True, "video_id": "v1"}


def test_playlist_list_dry_run_json() -> None:
    result = _invoke(["playlist", "list", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == {"dry_run": True}


def test_playlist_list_dry_run_plain() -> None:
    result = _invoke(["playlist", "list"])
    assert result.exit_code == 0
    assert "dry-run" in result.output


def test_comments_list_dry_run_json() -> None:
    result = _invoke(["comments", "list", "v1", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == {"dry_run": True, "video_id": "v1"}


def test_captions_list_dry_run_json() -> None:
    result = _invoke(["captions", "list", "v1", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == {"dry_run": True, "video_id": "v1"}


def test_channel_info_dry_run_json() -> None:
    result = _invoke(["channel", "info", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["dry_run"] is True
    assert "Нужен --no-dry-run" in data["message"]


def test_upload_prepare_plain(tmp_path: Path) -> None:
    f = tmp_path / "clip.bin"
    f.write_bytes(b"data")
    result = _invoke(["upload", "prepare", str(f), "--title", "T", "--privacy", "unlisted"])
    assert result.exit_code == 0
    assert "dry-run" in result.output.lower() or "План" in result.output
    assert "unlisted" in result.output


def test_upload_prepare_json(tmp_path: Path) -> None:
    f = tmp_path / "clip.bin"
    f.write_bytes(b"data")
    result = _invoke(["upload", "prepare", str(f), "--title", "T", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["ok"] is True
    assert data["plan"]["title"] == "T"
    assert data["video_id"] is None


def test_upload_prepare_no_notify_subscribers_json(tmp_path: Path) -> None:
    f = tmp_path / "clip.bin"
    f.write_bytes(b"data")
    result = _invoke(
        ["upload", "prepare", str(f), "--title", "T", "--no-notify-subscribers", "--json"]
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["plan"]["notify_subscribers"] is False


def test_upload_run_without_yes_refuses(tmp_path: Path) -> None:
    f = tmp_path / "clip.bin"
    f.write_bytes(b"data")
    result = _invoke(["upload", "run", str(f), "--title", "T", "--no-dry-run"])
    assert result.exit_code == 0
    assert "Нужны --no-dry-run и --yes" in result.output


def test_upload_run_dry_run_json(tmp_path: Path) -> None:
    f = tmp_path / "clip.bin"
    f.write_bytes(b"data")
    result = _invoke(["upload", "run", str(f), "--title", "T", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["dry_run"] is True


# --------------------------------------------------------------------------
# команды записи: --no-dry-run без --yes отказывают с понятным сообщением
# --------------------------------------------------------------------------


def test_write_commands_refuse_without_yes(tmp_path: Path) -> None:
    img = tmp_path / "cover.jpg"
    img.write_bytes(b"img")
    srt = tmp_path / "subs.srt"
    srt.write_text("1\n", encoding="utf-8")

    cases = [
        ["video", "publish", "v1", "--no-dry-run"],
        ["video", "schedule", "v1", "2026-10-01T15:00:00Z", "--no-dry-run"],
        ["video", "delete", "v1", "--no-dry-run"],
        ["video", "thumbnail", "v1", str(img), "--no-dry-run"],
        ["playlist", "create", "T", "--no-dry-run"],
        ["playlist", "add", "PL1", "v1", "--no-dry-run"],
        ["playlist", "delete", "PL1", "--no-dry-run"],
        ["comments", "reply", "c1", "hi", "--no-dry-run"],
        ["comments", "moderate", "c1", "rejected", "--no-dry-run"],
        ["captions", "upload", "v1", str(srt), "--no-dry-run"],
    ]
    runner = CliRunner()
    for args in cases:
        result = runner.invoke(cli, args)
        # Отказ обязан быть отличим от успеха: скрипт/агент не должен
        # принимать «изменения не отправлены» за «изменения применены».
        assert result.exit_code != 0, (args, result.output)
        assert REFUSAL in result.output, (args, result.output)


# --------------------------------------------------------------------------
# реальный путь через фейковый сервис
# --------------------------------------------------------------------------


def test_video_info_no_dry_run_plain(patch_service: dict[str, Any], fake_yt: FakeYT) -> None:
    result = _invoke(["video", "info", "v1", "--no-dry-run"], password=True)
    assert result.exit_code == 0
    assert "v1: Test video [private]" in result.output
    assert ("get_video", "v1", False) in fake_yt.calls
    assert patch_service["passphrase"] == "secret"


def test_video_info_no_dry_run_json(patch_service: dict[str, Any]) -> None:
    result = _invoke(["video", "info", "v1", "--no-dry-run", "--json"], password=True)
    assert result.exit_code == 0
    assert _json_from_output(result.output) == {
        "id": "v1",
        "title": "Test video",
        "privacy": "private",
    }


def test_video_info_no_dry_run_missing_video(
    patch_service: dict[str, Any], fake_yt: FakeYT
) -> None:
    result = _invoke(["video", "info", "bad", "--no-dry-run"], password=True)
    assert result.exit_code != 0
    assert isinstance(result.exception, ClientError)
    assert result.exception.code == "NOT_FOUND"


def test_playlist_list_no_dry_run_with_list(patch_service: dict[str, Any], fake_yt: FakeYT) -> None:
    result = _invoke(["playlist", "list", "--no-dry-run"], password=True)
    assert result.exit_code == 0
    assert "PL1" in result.output
    assert "List A" in result.output
    assert ("list_playlists", False) in fake_yt.calls


def test_playlist_list_no_dry_run_with_list_json(patch_service: dict[str, Any]) -> None:
    result = _invoke(["playlist", "list", "--no-dry-run", "--json"], password=True)
    assert result.exit_code == 0
    data = _json_from_output(result.output)
    assert isinstance(data, list)
    assert data[0]["id"] == "PL1"
    assert data[0]["items"] == 3


def test_playlist_list_no_dry_run_with_dict(patch_service: dict[str, Any], fake_yt: FakeYT) -> None:
    fake_yt.playlists_as_dict = True
    result = _invoke(["playlist", "list", "--no-dry-run"], password=True)
    assert result.exit_code == 0
    data = _json_from_output(result.output)
    assert isinstance(data, dict)
    assert data["dry_run"] is True


def test_comments_list_no_dry_run_with_list(patch_service: dict[str, Any], fake_yt: FakeYT) -> None:
    result = _invoke(["comments", "list", "v1", "--no-dry-run"], password=True)
    assert result.exit_code == 0
    assert "Alice" in result.output
    assert "c1" in result.output
    assert ("list_comment_threads", "v1", False) in fake_yt.calls


def test_comments_list_no_dry_run_with_list_json(patch_service: dict[str, Any]) -> None:
    result = _invoke(["comments", "list", "v1", "--no-dry-run", "--json"], password=True)
    assert result.exit_code == 0
    data = _json_from_output(result.output)
    assert isinstance(data, list)
    assert data[0] == {"id": "c1", "author": "Alice", "text": "Nice!"}


def test_comments_list_no_dry_run_with_dict(patch_service: dict[str, Any], fake_yt: FakeYT) -> None:
    fake_yt.comments_as_dict = True
    result = _invoke(["comments", "list", "v1", "--no-dry-run"], password=True)
    assert result.exit_code == 0
    data = _json_from_output(result.output)
    assert isinstance(data, dict)
    assert data["dry_run"] is True


def test_captions_list_no_dry_run_with_list(patch_service: dict[str, Any], fake_yt: FakeYT) -> None:
    result = _invoke(["captions", "list", "v1", "--no-dry-run"], password=True)
    assert result.exit_code == 0
    assert "cap1" in result.output
    assert "Русский" in result.output
    assert ("list_captions", "v1", False) in fake_yt.calls


def test_captions_list_no_dry_run_with_list_json(patch_service: dict[str, Any]) -> None:
    result = _invoke(["captions", "list", "v1", "--no-dry-run", "--json"], password=True)
    assert result.exit_code == 0
    data = _json_from_output(result.output)
    assert isinstance(data, list)
    assert data[0] == {"id": "cap1", "lang": "ru", "name": "Русский"}


def test_captions_list_no_dry_run_with_dict(patch_service: dict[str, Any], fake_yt: FakeYT) -> None:
    fake_yt.captions_as_dict = True
    result = _invoke(["captions", "list", "v1", "--no-dry-run"], password=True)
    assert result.exit_code == 0
    data = _json_from_output(result.output)
    assert isinstance(data, dict)
    assert data["dry_run"] is True


def test_channel_info_no_dry_run_plain(patch_service: dict[str, Any], fake_yt: FakeYT) -> None:
    result = _invoke(["channel", "info", "--no-dry-run"], password=True)
    assert result.exit_code == 0
    assert "UC_fake: My Channel (subs=42)" in result.output
    assert ("get_my_channel", False) in fake_yt.calls


def test_channel_info_no_dry_run_json(patch_service: dict[str, Any]) -> None:
    result = _invoke(["channel", "info", "--no-dry-run", "--json"], password=True)
    assert result.exit_code == 0
    assert _json_from_output(result.output) == {
        "id": "UC_fake",
        "title": "My Channel",
        "subscribers": 42,
    }


def test_upload_run_real_path_with_patched_executor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, patch_service: dict[str, Any]
) -> None:
    f = tmp_path / "clip.bin"
    f.write_bytes(b"data")
    captured: dict[str, Any] = {}

    def fake_execute(
        plan: Any, token: str, *, quota: Any = None, yes: bool = False, **kw: Any
    ) -> dict[str, Any]:
        captured.update(plan=plan, token=token, quota=quota, yes=yes)
        return {
            "ok": True,
            "dry_run": False,
            "video_id": "up1",
            "plan": plan.to_dict(),
            "raw": {"huge": "payload"},
        }

    monkeypatch.setattr(upload_mod, "execute_resumable_upload", fake_execute)
    result = _invoke(
        ["upload", "run", str(f), "--title", "T", "--no-dry-run", "--yes", "--json"],
        password=True,
    )
    assert result.exit_code == 0
    data = _json_from_output(result.output)
    assert data["video_id"] == "up1"
    assert "raw" not in data
    assert captured["token"] == "fake"
    assert captured["yes"] is True
    assert captured["plan"].dry_run is False
    assert captured["quota"] is not None


def test_upload_run_real_path_plain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, patch_service: dict[str, Any]
) -> None:
    f = tmp_path / "clip.bin"
    f.write_bytes(b"data")

    def fake_execute(
        plan: Any, token: str, *, quota: Any = None, yes: bool = False, **kw: Any
    ) -> dict[str, Any]:
        return {"ok": True, "video_id": "up2", "plan": plan.to_dict(), "raw": {}}

    monkeypatch.setattr(upload_mod, "execute_resumable_upload", fake_execute)
    result = _invoke(
        ["upload", "run", str(f), "--title", "T", "--no-dry-run", "--yes"],
        password=True,
    )
    assert result.exit_code == 0
    assert "upload OK video_id=up2" in result.output


def test_write_commands_succeed_with_fake_service(
    tmp_path: Path, patch_service: dict[str, Any], fake_yt: FakeYT
) -> None:
    img = tmp_path / "cover.jpg"
    img.write_bytes(b"img")
    srt = tmp_path / "subs.srt"
    srt.write_text("1\n", encoding="utf-8")

    cases = [
        (["video", "publish", "v1", "--no-dry-run", "--yes"], "publish_video"),
        (
            ["video", "schedule", "v1", "2026-10-01T15:00:00Z", "--no-dry-run", "--yes"],
            "schedule_video",
        ),
        (["video", "delete", "v1", "--no-dry-run", "--yes"], "delete_video"),
        (["video", "thumbnail", "v1", str(img), "--no-dry-run", "--yes"], "set_thumbnail"),
        (["playlist", "create", "New", "--no-dry-run", "--yes"], "create_playlist"),
        (["playlist", "add", "PL1", "v1", "--no-dry-run", "--yes"], "add_to_playlist"),
        (["playlist", "delete", "PL1", "--no-dry-run", "--yes"], "delete_playlist"),
        (["comments", "reply", "c1", "hi", "--no-dry-run", "--yes"], "reply_to_comment"),
        (
            ["comments", "moderate", "c1", "rejected", "--no-dry-run", "--yes"],
            "moderate_comment",
        ),
        (["captions", "upload", "v1", str(srt), "--no-dry-run", "--yes"], "upload_caption"),
    ]
    runner = CliRunner()
    for args, expected_call in cases:
        result = runner.invoke(cli, args, input=PASSWORD)
        assert result.exit_code == 0, (args, result.output)
        assert any(call[0] == expected_call for call in fake_yt.calls), expected_call

    assert "playlist create: PLNEW" in result.output or any(
        c[0] == "create_playlist" for c in fake_yt.calls
    )


# --------------------------------------------------------------------------
# AI-команды (офлайн-провайдер)
# --------------------------------------------------------------------------


def test_ai_commands_output() -> None:
    cases = [
        ["ai", "title", "python"],
        ["ai", "description", "python"],
        ["ai", "tags", "python"],
        ["ai", "script", "python"],
        ["ai", "thumbnail", "python"],
        ["ai", "chapters", "python"],
        ["ai", "translate", "hello"],
        ["ai", "calendar", "it"],
    ]
    runner = CliRunner()
    for args in cases:
        result = runner.invoke(cli, args)
        assert result.exit_code == 0, (args, result.output)
        assert result.output.strip() != ""


def test_ai_title_is_nonempty() -> None:
    result = _invoke(["ai", "title", "youtube automation"])
    assert result.exit_code == 0
    assert len(result.output.strip()) > 5


# --------------------------------------------------------------------------
# calendar / quota / doctor
# --------------------------------------------------------------------------


def test_calendar_add_then_list(tmp_path: Path) -> None:
    db = str(tmp_path / "calendar.db")
    added = _invoke(["calendar", "add", "v1", "Title", "2026-10-05T12:00:00Z", "--db", db])
    assert added.exit_code == 0
    assert "Добавлено: v1" in added.output

    listed = _invoke(["calendar", "list", "--db", db])
    assert listed.exit_code == 0
    assert "v1" in listed.output
    assert "Title" in listed.output


def test_calendar_list_empty(tmp_path: Path) -> None:
    result = _invoke(["calendar", "list", "--db", str(tmp_path / "empty.db")])
    assert result.exit_code == 0
    assert "Календарь пуст" in result.output


def test_calendar_list_json(tmp_path: Path) -> None:
    db = str(tmp_path / "calendar.db")
    _invoke(["calendar", "add", "v1", "Title", "2026-10-05T12:00:00Z", "--db", db])
    result = _invoke(["calendar", "list", "--db", db, "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data[0]["video_id"] == "v1"
    assert data[0]["title"] == "Title"
    assert data[0]["status"] == "scheduled"


def test_calendar_grid(tmp_path: Path) -> None:
    db = str(tmp_path / "calendar.db")
    _invoke(["calendar", "add", "v1", "A", "2026-10-05T12:00:00Z", "--db", db])
    result = _invoke(["calendar", "grid", "--db", db, "--year", "2026", "--month", "10"])
    assert result.exit_code == 0
    assert "2026-10" in result.output or "10" in result.output


def test_quota_status_plain(tmp_path: Path) -> None:
    result = _invoke(["quota", "status", "--db", str(tmp_path / "q.db")])
    assert result.exit_code == 0
    assert "Использовано" in result.output
    assert "Осталось" in result.output


def test_quota_status_json(tmp_path: Path) -> None:
    result = _invoke(["quota", "status", "--db", str(tmp_path / "q.db"), "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data == {"used": 0, "remaining": 10000, "limit": 10000}


def test_quota_status_json_limit(tmp_path: Path) -> None:
    result = _invoke(
        ["quota", "status", "--db", str(tmp_path / "q.db"), "--limit", "500", "--json"]
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["limit"] == 500
    assert data["remaining"] == 500


def test_doctor_plain() -> None:
    result = _invoke(["doctor"])
    assert result.exit_code == 0
    assert "версия" in result.output
    assert "config_dir" in result.output


def test_doctor_json() -> None:
    result = _invoke(["--log-level", "ERROR", "doctor", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["ok"] is True
    assert data["version"]
    assert data["checks"]["logging"] == "ok"
    assert data["checks"]["modules"]["quota"] == "ok"


def test_doctor_json_config_error_exits_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    import aiyoutubehands.config as config_mod

    def _boom() -> str:
        raise RuntimeError("config dir unavailable")

    monkeypatch.setattr(config_mod, "get_config_dir", _boom)
    result = _invoke(["--log-level", "ERROR", "doctor", "--json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["ok"] is False
    assert "config" in data["checks"]


# --------------------------------------------------------------------------
# ошибки ввода
# --------------------------------------------------------------------------


def test_video_thumbnail_missing_file_is_usage_error() -> None:
    result = _invoke(["video", "thumbnail", "v1", "/no/such/file.jpg"])
    assert result.exit_code == 2
    assert "Invalid value" in result.output


def test_captions_upload_missing_file_is_usage_error() -> None:
    result = _invoke(["captions", "upload", "v1", "/no/such/subs.srt"])
    assert result.exit_code == 2
    assert "Invalid value" in result.output


def test_upload_prepare_missing_file_is_usage_error() -> None:
    result = _invoke(["upload", "prepare", "/no/such/clip.mp4", "--title", "T"])
    assert result.exit_code == 2
    assert "Invalid value" in result.output


def test_upload_run_missing_file_is_usage_error() -> None:
    result = _invoke(["upload", "run", "/no/such/clip.mp4", "--title", "T"])
    assert result.exit_code == 2
    assert "Invalid value" in result.output


def test_comments_moderate_invalid_status_is_usage_error() -> None:
    result = _invoke(["comments", "moderate", "c1", "bogus"])
    assert result.exit_code == 2
    assert "Invalid value" in result.output


def test_upload_run_bad_privacy_is_usage_error(tmp_path: Path) -> None:
    f = tmp_path / "clip.bin"
    f.write_bytes(b"data")
    result = _invoke(["upload", "run", str(f), "--title", "T", "--privacy", "secret"])
    assert result.exit_code == 2
    assert "Invalid value" in result.output
