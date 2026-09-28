"""Флаг ``--ignore-markers``: осознанный обход маркера ПЕРЕДЕЛАТЬ автором.

Маркер ставит автоматический аудит звука в Shorts Maker. Он бывает ложным
(например, «clipping» при flat factor = 0). Правила процесса требуют пропускать
такие папки, поэтому обход возможен **только** явным флагом в командной строке,
а сам маркер остаётся зафиксирован в карточке папки для отчёта.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from click.testing import CliRunner

from aiyoutubehands.main import cli
from aiyoutubehands.shorts_maker.folder_scanner import scan_folder, scan_root

if TYPE_CHECKING:
    from pathlib import Path

PREFIX = "ш41 Почему мы боимся просить о помощи"


def _make_marked_folder(root: Path) -> Path:
    folder = root / PREFIX
    folder.mkdir()
    (folder / f"{PREFIX}_final.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")
    (folder / f"{PREFIX}_final_cover.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"x" * 120)
    (folder / f"{PREFIX}_titles.txt").write_text(
        "Заголовок: Почему мы боимся просить о помощи\nОписание: Описание из титров.\n",
        encoding="utf-8",
    )
    (folder / f"{PREFIX}_hashtags.txt").write_text("#психология #тест\n", encoding="utf-8")
    (folder / f"{PREFIX}_final_ПЕРЕДЕЛАТЬ.txt").write_text(
        "Видео помечено для переделки.\n\nПроблемы аудио:\n- clipping: обнаружено\n",
        encoding="utf-8",
    )
    return folder


def test_scan_folder_skips_marked_by_default(tmp_path: Path) -> None:
    """Без флага поведение прежнее: маркер → пропуск."""
    folder = _make_marked_folder(tmp_path)

    cand = scan_folder(folder)

    assert cand.skip_reason == "маркер ПЕРЕДЕЛАТЬ"
    assert cand.video_file is None, "при пропуске файлы не собираются"


def test_scan_folder_ignore_markers_collects_files(tmp_path: Path) -> None:
    """С флагом папка обрабатывается, но маркер всё равно виден в карточке."""
    folder = _make_marked_folder(tmp_path)

    cand = scan_folder(folder, ignore_markers=True)

    assert cand.skip_reason is None
    assert cand.video_file is not None
    assert cand.video_file.name == f"{PREFIX}_final.mp4"
    assert cand.cover is not None
    assert cand.cover.name == f"{PREFIX}_final_cover.jpg"
    assert cand.titles_txt is not None
    assert "ПЕРЕДЕЛАТЬ" in cand.markers, "маркер фиксируется для отчёта"


def test_scan_root_passes_flag_through(tmp_path: Path) -> None:
    """scan_root обязан передавать флаг дальше."""
    _make_marked_folder(tmp_path)

    assert scan_root(tmp_path)[0].skip_reason == "маркер ПЕРЕДЕЛАТЬ"
    assert scan_root(tmp_path, ignore_markers=True)[0].skip_reason is None


def test_other_markers_still_skip_when_ignoring(tmp_path: Path) -> None:
    """НУЖНО РАЗОБРАТЬСЯ — не неверный аудит, а «непонятная папка». Не обходим."""
    folder = _make_marked_folder(tmp_path)
    (folder / f"{PREFIX}_final_ПЕРЕДЕЛАТЬ.txt").unlink()
    (folder / "НУЖНО РАЗОБРАТЬСЯ.txt").write_text("разобраться\n", encoding="utf-8")

    cand = scan_folder(folder, ignore_markers=True)

    assert cand.skip_reason == "маркер НУЖНО РАЗОБРАТЬСЯ"


def test_cli_analyze_accepts_ignore_markers(tmp_path: Path, monkeypatch) -> None:
    """У `process analyze` должен быть флаг --ignore-markers."""
    _make_marked_folder(tmp_path)
    monkeypatch.setenv("AYH_PASSPHRASE", "pw")

    class _Quota:
        def check(self, *_a, **_k) -> None: ...

        def consume(self, *_a, **_k) -> None: ...

        def project(self, _ops) -> dict:
            return {"used": 0, "limit": 10000, "projected_total": 0, "would_exceed": False}

    class _YT:
        quota = _Quota()

        def list_channel_videos(self, **_k) -> list:
            return []

        def list_video_ids_in_playlists(self, **_k) -> set:
            return set()

    class _Client:
        def close(self) -> None: ...

    import aiyoutubehands.service_factory as sf

    monkeypatch.setattr(sf, "build_youtube_service", lambda **_k: (_YT(), _Client()))

    result = CliRunner().invoke(
        cli,
        [
            "process",
            "analyze",
            "--path",
            str(tmp_path),
            "--no-dry-run",
            "--ignore-markers",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "пропуск: маркер ПЕРЕДЕЛАТЬ" not in result.output, "папка не должна пропускаться"
    assert "проигнорирован" in result.output, "должно быть явное предупреждение"
