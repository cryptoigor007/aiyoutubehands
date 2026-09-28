"""Регресс-тесты на мелочи, найденные при написании покрытия.

Каждый тест соответствует пункту из раздела «Известные, сознательно не
исправленные мелочи» в AUDIT.md, который здесь закрывается.
"""

from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING

import pytest
from click.testing import CliRunner

from aiyoutubehands.main import cli

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# 1. auth status --json должен быть машиночитаемым и работать без TTY
# ---------------------------------------------------------------------------


def _seed_token(home: Path, passphrase: str) -> None:
    from aiyoutubehands.token import TokenData, TokenStore

    path = home / ".config" / "aiyoutubehands" / "token.age"
    TokenStore(path=path, passphrase=passphrase).save(
        TokenData(access_token="at", refresh_token="rt", expires_at=9999999999)
    )


def test_auth_status_json_is_machine_readable(tmp_path: Path, monkeypatch) -> None:
    """`auth status --json` не должен требовать TTY и не должен пачкать stdout.

    Регресс: пароль спрашивался через click.prompt, приглашение уходило в
    stdout перед JSON, а без интерактивного stdin команда падала с кодом 1.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("AYH_PASSPHRASE", "pw")
    _seed_token(tmp_path, "pw")

    result = CliRunner().invoke(cli, ["auth", "status", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True


def test_auth_status_without_passphrase_fails_clearly(tmp_path: Path, monkeypatch) -> None:
    """Без пароля и без TTY — понятная ошибка, а не мусор в stdout."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("AYH_PASSPHRASE", raising=False)
    _seed_token(tmp_path, "pw")

    result = CliRunner().invoke(cli, ["auth", "status", "--json"])

    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# 2. auth login не спрашивает пароль, если токен уже есть и нет --yes
# ---------------------------------------------------------------------------


def test_auth_login_does_not_prompt_when_token_exists(tmp_path: Path, monkeypatch) -> None:
    """Проверка «токен уже есть» должна быть ДО запроса пароля.

    Регресс: пароль спрашивался первым, и без интерактивного stdin команда
    падала с кодом 1 вместо понятного «передайте --yes» с кодом 2.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("AYH_PASSPHRASE", raising=False)
    _seed_token(tmp_path, "pw")

    result = CliRunner().invoke(cli, ["auth", "login"])

    assert result.exit_code == 2, result.output
    assert "уже есть" in result.output


# ---------------------------------------------------------------------------
# 3. handle_cli_error пишет в переданный поток
# ---------------------------------------------------------------------------


def test_handle_cli_error_uses_given_stream() -> None:
    """Параметр err должен использоваться, а не игнорироваться."""
    from aiyoutubehands.cli_errors import handle_cli_error

    stream = io.StringIO()
    code = handle_cli_error(ValueError("поломка"), err=stream)

    assert code != 0
    assert "поломка" in stream.getvalue()


# ---------------------------------------------------------------------------
# 4. find_repo_root без мёртвой ветки
# ---------------------------------------------------------------------------


def test_find_repo_root_finds_this_repo() -> None:
    """Репозиторий с docs/AGENT_PROMPT_PROCESS.md находится от файла модуля."""
    from aiyoutubehands.agent_rules import find_repo_root, rules_file_path

    root = find_repo_root()
    assert root is not None
    assert (root / "docs" / "AGENT_PROMPT_PROCESS.md").is_file()
    assert rules_file_path() is not None


# ---------------------------------------------------------------------------
# 5. fallback-логгер сохраняет correlation_id
# ---------------------------------------------------------------------------


def test_fallback_logger_reuses_correlation_id(monkeypatch) -> None:
    """Две записи подряд должны иметь один correlation_id.

    Регресс: _emit не сохранял сгенерированный id в ContextVar, поэтому каждая
    строка fallback-логов получала новый id и сквозная корреляция рвалась.
    """
    from aiyoutubehands import logging as log_mod

    monkeypatch.setattr(log_mod, "correlation_id_var", log_mod.correlation_id_var)
    log_mod.correlation_id_var.set("")

    payloads: list[dict] = []

    class _Recorder:
        def info(self, message: str) -> None:
            payloads.append(json.loads(message))

        def warning(self, message: str) -> None:
            payloads.append(json.loads(message))

    logger = log_mod._FallbackLogger("t")
    logger._log = _Recorder()
    logger.info("first")
    logger.info("second")

    assert len(payloads) == 2
    assert payloads[0]["correlation_id"] == payloads[1]["correlation_id"]
    assert log_mod.correlation_id_var.get() == payloads[0]["correlation_id"]


# ---------------------------------------------------------------------------
# 6. баннер безопасности: есть на голом `process`, не дублируется
# ---------------------------------------------------------------------------


def test_bare_process_prints_safety_banner() -> None:
    """`ayh process` без подкоманды обязан напоминать правила."""
    result = CliRunner().invoke(cli, ["process"])

    assert "ПРАВИЛА БЕЗОПАСНОСТИ" in result.output


def test_process_rules_prints_banner_once() -> None:
    """`ayh process rules` не должен печатать баннер дважды."""
    result = CliRunner().invoke(cli, ["process", "rules"])

    assert result.exit_code == 0, result.output
    assert result.output.count("ПРАВИЛА БЕЗОПАСНОСТИ") == 1


# ---------------------------------------------------------------------------
# 9. list_channel_videos не превышает max_results
# ---------------------------------------------------------------------------


def test_list_channel_videos_does_not_exceed_max_results(tmp_path: Path) -> None:
    """Даже если страница вернула больше запрошенного — результат обрезается."""
    import respx
    from httpx import Response

    from aiyoutubehands.client import HttpClient
    from aiyoutubehands.quota import QuotaEngine
    from aiyoutubehands.youtube import YoutubeService

    client = HttpClient(access_token="fake")
    yt = YoutubeService(client, QuotaEngine(db_path=tmp_path / "q.db"), "UC_test")

    def _video(i: int) -> dict:
        return {
            "id": f"v{i}",
            "snippet": {"title": f"t{i}", "publishedAt": "2026-09-27T00:00:00Z"},
            "status": {"privacyStatus": "private"},
            "contentDetails": {"duration": "PT10S"},
            "processingDetails": {"processingStatus": "succeeded"},
        }

    with respx.mock:
        respx.get("https://www.googleapis.com/youtube/v3/channels").mock(
            return_value=Response(
                200,
                json={
                    "items": [
                        {
                            "id": "UC_test",
                            "snippet": {"title": "T"},
                            "contentDetails": {"relatedPlaylists": {"uploads": "UU1"}},
                        }
                    ]
                },
            )
        )
        respx.get("https://www.googleapis.com/youtube/v3/playlistItems").mock(
            return_value=Response(
                200,
                json={
                    "items": [
                        {
                            "snippet": {
                                "publishedAt": "2026-09-27T00:00:00Z",
                                "resourceId": {"videoId": f"v{i}"},
                            }
                        }
                        for i in range(3)
                    ]
                },
            )
        )
        respx.get("https://www.googleapis.com/youtube/v3/videos").mock(
            return_value=Response(200, json={"items": [_video(0), _video(1), _video(2)]})
        )

        out = yt.list_channel_videos(max_results=2, max_age_days=3650, dry_run=False)

    assert [v.id for v in out] == ["v0", "v1"]


# ---------------------------------------------------------------------------
# 7. apply --dry-run должен показывать план, а не «Нет видео для обработки»
# ---------------------------------------------------------------------------


def _saved_plan(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "created_at": "2026-09-28T00:00:00+03:00",
                "root_path": "/tmp/sm",
                "confirm_phrase": "подтверждаю план от 28.09.2026 #abc123abc123",
                "fingerprint": "abc123abc123",
                "items": [
                    {
                        "video_id": "vid1",
                        "status": "к обработке",
                        "new_title": "Новый заголовок",
                    },
                    {"video_id": None, "status": "пропуск: не сопоставлено", "new_title": ""},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def test_apply_dry_run_with_plan_previews_offline(tmp_path: Path, monkeypatch) -> None:
    """`apply --dry-run --plan` показывает сохранённый план без обращения к сети."""
    import aiyoutubehands.service_factory as sf

    def _boom(*_a, **_k):
        raise AssertionError("dry-run не должен ходить в сеть")

    monkeypatch.setattr(sf, "build_youtube_service", _boom)
    plan_file = _saved_plan(tmp_path / "plan.json")

    result = CliRunner().invoke(
        cli,
        ["process", "apply", "--path", str(tmp_path), "--plan", str(plan_file), "--dry-run"],
    )

    assert result.exit_code == 0, result.output
    assert "vid1" in result.output
    assert "Новый заголовок" in result.output
    assert "abc123abc123" in result.output


def test_apply_dry_run_without_plan_explains_how_to_preview(tmp_path: Path) -> None:
    """Без --plan dry-run не может построить план — надо сказать, что делать."""
    result = CliRunner().invoke(cli, ["process", "apply", "--path", str(tmp_path), "--dry-run"])

    assert result.exit_code != 0
    assert "analyze" in result.output


def test_apply_non_dry_run_requires_confirm(tmp_path: Path) -> None:
    """Для реального применения фраза подтверждения обязательна."""
    result = CliRunner().invoke(
        cli,
        ["process", "apply", "--path", str(tmp_path), "--no-dry-run", "--yes"],
    )

    assert result.exit_code != 0
    assert "--confirm" in result.output


# ---------------------------------------------------------------------------
# 8. resumable upload: порядок проверок, Range из 308, неполный финальный чанк
# ---------------------------------------------------------------------------


class _UploadHTTP:
    """Фейковый httpx.Client для execute_resumable_upload."""

    def __init__(self, script: list, calls: list) -> None:
        self._script = script
        self._calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *_a) -> bool:
        return False

    def post(self, url, **kwargs):
        self._calls.append(("post", url, kwargs))
        return self._script.pop(0)

    def put(self, url, **kwargs):
        self._calls.append(("put", url, kwargs))
        return self._script.pop(0)


class _R:
    def __init__(self, status_code: int, *, headers: dict | None = None, payload=None) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self.text = ""
        self.content = b"{}"
        self._payload = payload if payload is not None else {"id": "newvid"}

    def json(self):
        return self._payload


def _install_upload_http(monkeypatch, tmp_path: Path, script: list) -> list:
    from aiyoutubehands import upload as upload_mod

    calls: list = []
    monkeypatch.setattr(upload_mod.httpx, "Client", lambda *_a, **_k: _UploadHTTP(script, calls))
    return calls


def test_upload_checks_token_before_quota(tmp_path: Path, monkeypatch) -> None:
    """Пустой токен — раньше проверки квоты, иначе наружу уйдёт неверная ошибка."""
    from aiyoutubehands.quota import QuotaEngine
    from aiyoutubehands.upload import UploadError, execute_resumable_upload, prepare_upload

    calls = _install_upload_http(monkeypatch, tmp_path, [])
    f = tmp_path / "v.bin"
    f.write_bytes(b"data")
    plan = prepare_upload(f, title="T", dry_run=False)
    quota = QuotaEngine(db_path=tmp_path / "q.db", daily_limit=0)

    with pytest.raises(UploadError) as ei:
        execute_resumable_upload(plan, access_token="", quota=quota, yes=True)

    assert ei.value.code == "NOT_AUTHENTICATED"
    assert calls == []


def test_upload_uses_range_from_308(tmp_path: Path, monkeypatch) -> None:
    """308 c Range: сколько байт сервер принял, оттуда и продолжаем."""
    from aiyoutubehands.upload import execute_resumable_upload, prepare_upload

    calls = _install_upload_http(
        monkeypatch,
        tmp_path,
        [
            _R(200, headers={"Location": "https://upload.test/s1"}),
            _R(308, headers={"Range": "bytes=0-3"}),
            _R(200, payload={"id": "final"}),
        ],
    )
    f = tmp_path / "v.bin"
    f.write_bytes(b"0123456789")
    plan = prepare_upload(f, title="T", dry_run=False)

    result = execute_resumable_upload(plan, access_token="t", yes=True, chunk_size=8)

    assert result["video_id"] == "final"
    second_range = calls[2][2]["headers"]["Content-Range"]
    assert second_range == "bytes 4-9/10"


def test_upload_rejects_incomplete_final_chunk(tmp_path: Path, monkeypatch) -> None:
    """200 на частичный чанк — это потеря данных, а не успех."""
    from aiyoutubehands.upload import UploadError, execute_resumable_upload, prepare_upload

    _install_upload_http(
        monkeypatch,
        tmp_path,
        [
            _R(200, headers={"Location": "https://upload.test/s1"}),
            _R(200, payload={"id": "partial"}),
        ],
    )
    f = tmp_path / "v.bin"
    f.write_bytes(b"0123456789")
    plan = prepare_upload(f, title="T", dry_run=False)
    # План считает, что файл длиннее, чем есть на диске.
    plan.size = 20

    with pytest.raises(UploadError) as ei:
        execute_resumable_upload(plan, access_token="t", yes=True, chunk_size=8)

    assert ei.value.code == "UPLOAD_INCOMPLETE"
