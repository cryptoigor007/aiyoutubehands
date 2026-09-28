"""Дополнительные тесты shorts_maker: media.py и metadata_extractor.py.

Покрывают ветки, не затронутые ``tests/test_shorts_maker.py``:

* ``media.probe_duration_seconds`` / ``probe_is_vertical`` / ``is_likely_short``
  — разбор вывода ffprobe через замоканный ``subprocess.run`` / ``shutil.which``
  (реальный ffprobe не требуется, сеть не используется);
* ``metadata_extractor.extract_metadata`` и его приватные помощники — приоритет
  источников, обрезка длин, битый JSON, локальная AI-заглушка.

Существующий ``tests/conftest.py`` изолирует HOME/XDG до импорта пакета.
"""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING, Any

import pytest

import aiyoutubehands.shorts_maker.media as media_mod
from aiyoutubehands.shorts_maker.folder_scanner import (
    FolderCandidate,
    clean_folder_title,
    scan_folder,
)
from aiyoutubehands.shorts_maker.media import (
    is_likely_short,
    probe_duration_seconds,
    probe_is_vertical,
)
from aiyoutubehands.shorts_maker.metadata_extractor import (
    _description_from_editing_plan,
    _description_from_titles_txt,
    _hashtags_from_editing_plan,
    _load_json,
    _tags_from_hashtags_txt,
    _trim_tags,
    extract_metadata,
)

if TYPE_CHECKING:
    from pathlib import Path


# --------------------------------------------------------------------------- #
# Помощники
# --------------------------------------------------------------------------- #


def _make_folder(
    root: Path,
    name: str,
    *,
    mp4: bool = True,
    cover: bool = True,
    titles: str | None = None,
    hashtags: str | None = None,
    editing_plan: dict[str, Any] | None = None,
    final_aisie_plan: dict[str, Any] | None = None,
    hooks: str | None = None,
) -> Path:
    """Создать папку Shorts Maker с типовым набором файлов."""
    d = root / name
    d.mkdir(parents=True)
    prefix = name.split()[0] if name else "ш1"
    if mp4:
        (d / f"{prefix}_clip.mp4").write_bytes(b"fake")
    if cover:
        (d / f"{prefix}_final_cover.jpg").write_bytes(b"\xff\xd8\xff")
    if titles is not None:
        (d / f"{prefix}_titles.txt").write_text(titles, encoding="utf-8")
    if hashtags is not None:
        (d / f"{prefix}_hashtags.txt").write_text(hashtags, encoding="utf-8")
    if editing_plan is not None:
        (d / f"{prefix}_editing_plan.json").write_text(
            json.dumps(editing_plan, ensure_ascii=False), encoding="utf-8"
        )
    if final_aisie_plan is not None:
        (d / f"{prefix}_final_aisie_plan.json").write_text(
            json.dumps(final_aisie_plan, ensure_ascii=False), encoding="utf-8"
        )
    if hooks is not None:
        (d / f"{prefix}_hooks.txt").write_text(hooks, encoding="utf-8")
    return d


def _write_json(path: Path, payload: Any) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _no_ffprobe_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    """По умолчанию ffprobe «не установлен» — тесты детерминированы."""
    monkeypatch.setattr(media_mod.shutil, "which", lambda _name: None)


def _set_which(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    monkeypatch.setattr(media_mod.shutil, "which", lambda _name: value)


class _FakeProc:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _set_run(
    monkeypatch: pytest.MonkeyPatch,
    proc: _FakeProc | None = None,
    *,
    exc: BaseException | None = None,
) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: Any) -> _FakeProc:
        calls.append(list(cmd))
        if exc is not None:
            raise exc
        assert proc is not None
        return proc

    monkeypatch.setattr(media_mod.subprocess, "run", fake_run)
    return calls


def _patch_probes(
    monkeypatch: pytest.MonkeyPatch, *, dur: int | None, vertical: bool | None
) -> list[str]:
    calls: list[str] = []

    def fake_dur(_path: Path | str) -> int | None:
        calls.append("duration")
        return dur

    def fake_vert(_path: Path | str) -> bool | None:
        calls.append("vertical")
        return vertical

    monkeypatch.setattr(media_mod, "probe_duration_seconds", fake_dur)
    monkeypatch.setattr(media_mod, "probe_is_vertical", fake_vert)
    return calls


# --------------------------------------------------------------------------- #
# media.probe_duration_seconds
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("stdout", "expected"),
    [
        ('{"format": {"duration": "12.6"}}', 13),
        ('{"format": {"duration": "44.4"}}', 44),
        ('{"format": {"duration": "44.6"}}', 45),
        ('{"format": {"duration": "60"}}', 60),
        ('{"format": {"duration": "0.2"}}', 0),
    ],
)
def test_probe_duration_parses_and_rounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stdout: str, expected: int
) -> None:
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"x")
    _set_which(monkeypatch, "/usr/bin/ffprobe")
    calls = _set_run(monkeypatch, _FakeProc(stdout=stdout))

    assert probe_duration_seconds(f) == expected
    assert len(calls) == 1
    assert str(f) in calls[0]


def test_probe_duration_accepts_str_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"x")
    _set_which(monkeypatch, "/usr/bin/ffprobe")
    _set_run(monkeypatch, _FakeProc(stdout='{"format": {"duration": "15"}}'))

    assert probe_duration_seconds(str(f)) == 15


def test_probe_duration_file_missing_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_which(monkeypatch, "/usr/bin/ffprobe")
    calls = _set_run(monkeypatch, _FakeProc(stdout='{"format": {"duration": "15"}}'))

    assert probe_duration_seconds(tmp_path / "nope.mp4") is None
    assert calls == []


def test_probe_duration_ffprobe_absent_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"x")
    _set_which(monkeypatch, None)
    calls = _set_run(monkeypatch, _FakeProc(stdout='{"format": {"duration": "15"}}'))

    assert probe_duration_seconds(f) is None
    assert calls == []


def test_probe_duration_file_not_found_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"x")
    _set_which(monkeypatch, "/usr/bin/ffprobe")
    _set_run(monkeypatch, exc=FileNotFoundError("ffprobe not found"))

    assert probe_duration_seconds(f) is None


def test_probe_duration_nonzero_returncode_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"x")
    _set_which(monkeypatch, "/usr/bin/ffprobe")
    _set_run(monkeypatch, _FakeProc(stdout="", stderr="boom", returncode=1))

    assert probe_duration_seconds(f) is None


def test_probe_duration_garbage_stdout_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"x")
    _set_which(monkeypatch, "/usr/bin/ffprobe")
    _set_run(monkeypatch, _FakeProc(stdout="not json at all", returncode=0))

    assert probe_duration_seconds(f) is None


@pytest.mark.parametrize("stdout", ["{}", '{"format": {}}', '{"format": null}'])
def test_probe_duration_missing_duration_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stdout: str
) -> None:
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"x")
    _set_which(monkeypatch, "/usr/bin/ffprobe")
    _set_run(monkeypatch, _FakeProc(stdout=stdout))

    assert probe_duration_seconds(f) is None


def test_probe_duration_invalid_float_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"x")
    _set_which(monkeypatch, "/usr/bin/ffprobe")
    _set_run(monkeypatch, _FakeProc(stdout='{"format": {"duration": "abc"}}'))

    assert probe_duration_seconds(f) is None


def test_probe_duration_timeout_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"x")
    _set_which(monkeypatch, "/usr/bin/ffprobe")
    _set_run(monkeypatch, exc=subprocess.TimeoutExpired(cmd="ffprobe", timeout=30))

    assert probe_duration_seconds(f) is None


def test_probe_duration_oserror_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"x")
    _set_which(monkeypatch, "/usr/bin/ffprobe")
    _set_run(monkeypatch, exc=OSError("exec failed"))

    assert probe_duration_seconds(f) is None


# --------------------------------------------------------------------------- #
# media.probe_is_vertical
# --------------------------------------------------------------------------- #


def _vertical_proc(width: int, height: int) -> _FakeProc:
    return _FakeProc(stdout=json.dumps({"streams": [{"width": width, "height": height}]}))


def test_probe_is_vertical_true_for_portrait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"x")
    _set_which(monkeypatch, "/usr/bin/ffprobe")
    _set_run(monkeypatch, _vertical_proc(1080, 1920))

    assert probe_is_vertical(f) is True


def test_probe_is_vertical_false_for_landscape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"x")
    _set_which(monkeypatch, "/usr/bin/ffprobe")
    _set_run(monkeypatch, _vertical_proc(1920, 1080))

    assert probe_is_vertical(f) is False


def test_probe_is_vertical_false_for_square(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"x")
    _set_which(monkeypatch, "/usr/bin/ffprobe")
    _set_run(monkeypatch, _vertical_proc(720, 720))

    assert probe_is_vertical(f) is False


@pytest.mark.parametrize("stdout", ["{}", '{"streams": []}', '{"streams": null}'])
def test_probe_is_vertical_no_streams_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stdout: str
) -> None:
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"x")
    _set_which(monkeypatch, "/usr/bin/ffprobe")
    _set_run(monkeypatch, _FakeProc(stdout=stdout))

    assert probe_is_vertical(f) is None


@pytest.mark.parametrize(
    "stream",
    [
        {"width": 0, "height": 1920},
        {"width": 1080, "height": 0},
        {"height": 1920},
        {"width": 1080},
    ],
)
def test_probe_is_vertical_zero_dimensions_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stream: dict[str, int]
) -> None:
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"x")
    _set_which(monkeypatch, "/usr/bin/ffprobe")
    _set_run(monkeypatch, _FakeProc(stdout=json.dumps({"streams": [stream]})))

    assert probe_is_vertical(f) is None


def test_probe_is_vertical_nonzero_returncode_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"x")
    _set_which(monkeypatch, "/usr/bin/ffprobe")
    _set_run(monkeypatch, _FakeProc(stdout="", stderr="bad", returncode=1))

    assert probe_is_vertical(f) is None


def test_probe_is_vertical_garbage_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"x")
    _set_which(monkeypatch, "/usr/bin/ffprobe")
    _set_run(monkeypatch, _FakeProc(stdout="{not json", returncode=0))

    assert probe_is_vertical(f) is None


def test_probe_is_vertical_type_error_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"x")
    _set_which(monkeypatch, "/usr/bin/ffprobe")
    _set_run(
        monkeypatch,
        _FakeProc(stdout=json.dumps({"streams": [{"width": {"bad": 1}, "height": 10}]})),
    )

    assert probe_is_vertical(f) is None


def test_probe_is_vertical_file_missing_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_which(monkeypatch, "/usr/bin/ffprobe")
    calls = _set_run(monkeypatch, _vertical_proc(1080, 1920))

    assert probe_is_vertical(tmp_path / "nope.mp4") is None
    assert calls == []


def test_probe_is_vertical_ffprobe_absent_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"x")
    _set_which(monkeypatch, None)
    calls = _set_run(monkeypatch, _vertical_proc(1080, 1920))

    assert probe_is_vertical(f) is None
    assert calls == []


# --------------------------------------------------------------------------- #
# media.is_likely_short
# --------------------------------------------------------------------------- #


def test_is_likely_short_missing_file_returns_none(tmp_path: Path) -> None:
    assert is_likely_short(tmp_path / "nope.mp4") is None


def test_is_likely_short_duration_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_probes(monkeypatch, dur=None, vertical=True)

    assert is_likely_short(tmp_path / "x.mp4") is None
    assert calls == ["duration"]


def test_is_likely_short_too_long_is_false(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_probes(monkeypatch, dur=61, vertical=True)

    assert is_likely_short(tmp_path / "x.mp4") is False
    # при превышении длительности вертикаль не проверяется
    assert calls == ["duration"]


def test_is_likely_short_vertical_true(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_probes(monkeypatch, dur=30, vertical=True)

    assert is_likely_short(tmp_path / "x.mp4") is True
    assert calls == ["duration", "vertical"]


def test_is_likely_short_vertical_false(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_probes(monkeypatch, dur=30, vertical=False)

    assert is_likely_short(tmp_path / "x.mp4") is False


def test_is_likely_short_vertical_unknown_falls_back_to_duration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_probes(monkeypatch, dur=30, vertical=None)
    assert is_likely_short(tmp_path / "x.mp4") is True

    _patch_probes(monkeypatch, dur=90, vertical=None)
    assert is_likely_short(tmp_path / "x.mp4") is False


def test_is_likely_short_boundary_60_seconds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_probes(monkeypatch, dur=60, vertical=True)
    assert is_likely_short(tmp_path / "x.mp4") is True

    _patch_probes(monkeypatch, dur=60, vertical=None)
    assert is_likely_short(tmp_path / "x.mp4") is True

    _patch_probes(monkeypatch, dur=60, vertical=False)
    assert is_likely_short(tmp_path / "x.mp4") is False


def test_is_likely_short_custom_max_seconds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_probes(monkeypatch, dur=90, vertical=True)
    assert is_likely_short(tmp_path / "x.mp4", max_seconds=120) is True

    _patch_probes(monkeypatch, dur=120, vertical=True)
    assert is_likely_short(tmp_path / "x.mp4", max_seconds=120) is True

    _patch_probes(monkeypatch, dur=121, vertical=True)
    assert is_likely_short(tmp_path / "x.mp4", max_seconds=120) is False


@pytest.mark.parametrize(
    ("duration", "dims", "expected"),
    [
        ("30.0", (1080, 1920), True),
        ("90.0", (1080, 1920), False),
        ("30.0", (1920, 1080), False),
        ("30.0", None, True),  # вертикаль не определяется → duration-only
    ],
)
def test_is_likely_short_end_to_end_mocked_ffprobe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    duration: str,
    dims: tuple[int, int] | None,
    expected: bool,
) -> None:
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"x")
    _set_which(monkeypatch, "/usr/bin/ffprobe")

    def fake_run(cmd: list[str], **_kwargs: Any) -> _FakeProc:
        if "format=duration" in cmd:
            return _FakeProc(stdout=json.dumps({"format": {"duration": duration}}))
        if "stream=width,height" in cmd:
            if dims is None:
                return _FakeProc(returncode=1, stderr="no video stream")
            w, h = dims
            return _FakeProc(stdout=json.dumps({"streams": [{"width": w, "height": h}]}))
        return _FakeProc(returncode=1, stderr="unexpected")

    monkeypatch.setattr(media_mod.subprocess, "run", fake_run)

    assert is_likely_short(f) is expected


# --------------------------------------------------------------------------- #
# metadata_extractor._load_json
# --------------------------------------------------------------------------- #


def test_load_json_valid_dict_and_list(tmp_path: Path) -> None:
    d = _write_json(tmp_path / "a.json", {"x": 1})
    lst = _write_json(tmp_path / "b.json", [1, 2])

    assert _load_json(d) == {"x": 1}
    assert _load_json(lst) == [1, 2]


@pytest.mark.parametrize("raw", ["123", '"string"', "true", "null", "3.14"])
def test_load_json_rejects_scalar_values(tmp_path: Path, raw: str) -> None:
    p = tmp_path / "scalar.json"
    p.write_text(raw, encoding="utf-8")

    assert _load_json(p) is None


def test_load_json_rejects_malformed(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")

    assert _load_json(p) is None


def test_load_json_missing_file_returns_none(tmp_path: Path) -> None:
    assert _load_json(tmp_path / "missing.json") is None


# --------------------------------------------------------------------------- #
# metadata_extractor: title
# --------------------------------------------------------------------------- #


def test_extract_title_truncated_to_100(tmp_path: Path) -> None:
    long_title = "Ж" * 150
    cand = FolderCandidate(path=tmp_path, folder_name=f"ш1 {long_title}", clean_title=long_title)

    meta = extract_metadata(cand)

    assert meta.title == long_title[:100]
    assert len(meta.title) == 100
    assert "title:folder/mp4" in meta.source_notes


def test_extract_title_from_video_stem_when_clean_title_empty(tmp_path: Path) -> None:
    video = tmp_path / "My Cool Video.mp4"
    cand = FolderCandidate(path=tmp_path, folder_name="", clean_title="", video_file=video)

    meta = extract_metadata(cand)

    assert meta.title == clean_folder_title(video.stem) == "My Cool Video"


def test_extract_title_untitled_when_no_name(tmp_path: Path) -> None:
    cand = FolderCandidate(path=tmp_path, folder_name="", clean_title="")

    meta = extract_metadata(cand)

    assert meta.title == "Untitled"


# --------------------------------------------------------------------------- #
# metadata_extractor: description
# --------------------------------------------------------------------------- #


def test_extract_description_priority_editing_plan(tmp_path: Path) -> None:
    plan = _write_json(
        tmp_path / "p_editing_plan.json",
        {"clips": [{"description": "Описание из editing_plan"}]},
    )
    aisie = _write_json(
        tmp_path / "p_final_aisie_plan.json",
        {"clips": [{"description": "Описание из final_aisie_plan"}]},
    )
    titles = tmp_path / "p_titles.txt"
    titles.write_text("Заголовок\n\nОписание из titles", encoding="utf-8")
    cand = FolderCandidate(
        path=tmp_path,
        folder_name="ш1 P",
        clean_title="P",
        editing_plan=plan,
        final_aisie_plan=aisie,
        titles_txt=titles,
    )

    meta = extract_metadata(cand)

    assert meta.description == "Описание из editing_plan"
    assert "description:editing_plan" in meta.source_notes
    assert "description:final_aisie_plan" not in meta.source_notes
    assert "description:titles_txt" not in meta.source_notes


def test_extract_description_falls_back_to_final_aisie_plan(tmp_path: Path) -> None:
    plan = _write_json(tmp_path / "p_editing_plan.json", {"clips": [{"description": "   "}]})
    aisie = _write_json(
        tmp_path / "p_final_aisie_plan.json",
        {"clips": [{"description": "Описание из aisie"}]},
    )
    cand = FolderCandidate(
        path=tmp_path,
        folder_name="ш1 P",
        clean_title="P",
        editing_plan=plan,
        final_aisie_plan=aisie,
    )

    meta = extract_metadata(cand)

    assert meta.description == "Описание из aisie"
    assert "description:final_aisie_plan" in meta.source_notes
    assert "description:editing_plan" not in meta.source_notes


def test_extract_description_falls_back_to_titles_txt(tmp_path: Path) -> None:
    titles = tmp_path / "p_titles.txt"
    titles.write_text("Заголовок\n\nОписание из titles", encoding="utf-8")
    cand = FolderCandidate(path=tmp_path, folder_name="ш1 P", clean_title="P", titles_txt=titles)

    meta = extract_metadata(cand)

    assert meta.description == "Описание из titles"
    assert "description:titles_txt" in meta.source_notes


def test_extract_description_truncated_to_5000(tmp_path: Path) -> None:
    plan = _write_json(tmp_path / "p_editing_plan.json", {"clips": [{"description": "D" * 6000}]})
    cand = FolderCandidate(path=tmp_path, folder_name="ш1 P", clean_title="P", editing_plan=plan)

    meta = extract_metadata(cand)

    assert len(meta.description) == 5000
    assert meta.description == "D" * 5000


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"clips": [{"description": "clip desc"}]}, "clip desc"),
        ({"clips": [{"desc": "clip desc2"}]}, "clip desc2"),
        ({"clips": [], "description": "top desc"}, "top desc"),
        ({"clips": [], "desc": "top desc2"}, "top desc2"),
        ({"clips": [{"x": 1}], "description": "fallback"}, "fallback"),
        ({"clips": [{"description": "   "}], "description": "after blank"}, "after blank"),
        ({"description": "   "}, None),
        ({"clips": "не список"}, None),
        ({}, None),
        ([1, 2], None),
    ],
)
def test_description_from_editing_plan_variants(
    tmp_path: Path, payload: Any, expected: str | None
) -> None:
    p = _write_json(tmp_path / "plan.json", payload)
    assert _description_from_editing_plan(p) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Заголовок\n\nПервая строка\nвторая", "Первая строка вторая"),
        ("Заголовок\nСтрока сразу\n\nпосле", "Строка сразу"),
        ("x" * 50, "x" * 50),
        ("only title", None),
        ("", None),
    ],
)
def test_description_from_titles_txt_variants(
    tmp_path: Path, text: str, expected: str | None
) -> None:
    p = tmp_path / "titles.txt"
    p.write_text(text, encoding="utf-8")
    assert _description_from_titles_txt(p) == expected


# --------------------------------------------------------------------------- #
# metadata_extractor: tags
# --------------------------------------------------------------------------- #


def test_extract_tags_priority_hashtags_txt(tmp_path: Path) -> None:
    hashtags = tmp_path / "p_hashtags.txt"
    hashtags.write_text("#shorts #тег", encoding="utf-8")
    plan = _write_json(tmp_path / "p_editing_plan.json", {"tags": ["изплана"]})
    cand = FolderCandidate(
        path=tmp_path,
        folder_name="ш1 P",
        clean_title="P",
        hashtags_txt=hashtags,
        editing_plan=plan,
    )

    meta = extract_metadata(cand)

    assert meta.tags == ["shorts", "тег"]
    assert "tags:hashtags_txt" in meta.source_notes
    assert "tags:editing_plan" not in meta.source_notes


def test_extract_tags_falls_back_to_editing_plan(tmp_path: Path) -> None:
    plan = _write_json(tmp_path / "p_editing_plan.json", {"tags": ["plan1", "plan2"]})
    cand = FolderCandidate(path=tmp_path, folder_name="ш1 P", clean_title="P", editing_plan=plan)

    meta = extract_metadata(cand)

    assert meta.tags == ["plan1", "plan2"]
    assert "tags:editing_plan" in meta.source_notes


def test_extract_tags_falls_back_to_final_aisie_plan(tmp_path: Path) -> None:
    aisie = _write_json(tmp_path / "p_final_aisie_plan.json", {"clips": [{"hashtags": ["#aisie"]}]})
    cand = FolderCandidate(
        path=tmp_path, folder_name="ш1 P", clean_title="P", final_aisie_plan=aisie
    )

    meta = extract_metadata(cand)

    assert meta.tags == ["aisie"]
    assert "tags:final_aisie_plan" in meta.source_notes


def test_extract_empty_hashtags_falls_through_to_plan(tmp_path: Path) -> None:
    hashtags = tmp_path / "p_hashtags.txt"
    hashtags.write_text("http://example.com/only", encoding="utf-8")
    plan = _write_json(tmp_path / "p_editing_plan.json", {"tags": ["изплана"]})
    cand = FolderCandidate(
        path=tmp_path,
        folder_name="ш1 P",
        clean_title="P",
        hashtags_txt=hashtags,
        editing_plan=plan,
    )

    meta = extract_metadata(cand)

    assert meta.tags == ["изплана"]
    assert "tags:hashtags_txt" not in meta.source_notes
    assert "tags:editing_plan" in meta.source_notes


def test_extract_tags_trimmed_to_500_chars(tmp_path: Path) -> None:
    hashtags = tmp_path / "p_hashtags.txt"
    hashtags.write_text(" ".join(["a" * 200, "b" * 200, "c" * 200]), encoding="utf-8")
    cand = FolderCandidate(
        path=tmp_path, folder_name="ш1 P", clean_title="P", hashtags_txt=hashtags
    )

    meta = extract_metadata(cand)

    assert len(meta.tags) == 2
    assert len(",".join(meta.tags)) <= 500


def test_tags_from_hashtags_txt_parsing(tmp_path: Path) -> None:
    p = tmp_path / "h.txt"
    p.write_text("#Shorts, #мотивация http://x.com\n#dup #DUP", encoding="utf-8")

    assert _tags_from_hashtags_txt(p) == ["Shorts", "мотивация", "dup"]


def test_tags_from_hashtags_txt_missing_file(tmp_path: Path) -> None:
    assert _tags_from_hashtags_txt(tmp_path / "missing.txt") == []


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"clips": [{"hashtags": ["#a", "b"]}], "tags": ["c"]}, ["a", "b", "c"]),
        ({"clips": [{"tags": "#x, y z"}]}, ["x", "y", "z"]),
        ({"clips": [{"hashtags": "#m #M"}], "hashtags": ["#n"]}, ["m", "n"]),
        ({"tags": ["A", "a"]}, ["A"]),
        ([], []),
    ],
)
def test_hashtags_from_editing_plan_variants(
    tmp_path: Path, payload: Any, expected: list[str]
) -> None:
    p = _write_json(tmp_path / "plan.json", payload)
    assert _hashtags_from_editing_plan(p) == expected


def test_trim_tags_boundaries() -> None:
    assert _trim_tags([]) == []
    assert _trim_tags(["x"]) == ["x"]
    assert _trim_tags(["a" * 249, "b" * 249]) == ["a" * 249, "b" * 249]
    assert _trim_tags(["a" * 250, "b" * 250]) == ["a" * 250]


# --------------------------------------------------------------------------- #
# metadata_extractor: notes / thumbnail / битый JSON
# --------------------------------------------------------------------------- #


def test_extract_source_notes_full(tmp_path: Path) -> None:
    plan = _write_json(tmp_path / "p_editing_plan.json", {"clips": [{"description": "Из плана"}]})
    hashtags = tmp_path / "p_hashtags.txt"
    hashtags.write_text("#shorts #тег", encoding="utf-8")
    cover = tmp_path / "p_final_cover.jpg"
    cover.write_bytes(b"\xff\xd8\xff")
    hooks = tmp_path / "p_hooks.txt"
    hooks.write_text("Хук", encoding="utf-8")
    cand = FolderCandidate(
        path=tmp_path,
        folder_name="ш1 P",
        clean_title="P",
        editing_plan=plan,
        hashtags_txt=hashtags,
        cover=cover,
        hooks_txt=hooks,
    )

    meta = extract_metadata(cand)

    for note in (
        "title:folder/mp4",
        "description:editing_plan",
        "tags:hashtags_txt",
        "thumbnail:final_cover",
        "hooks:present",
    ):
        assert note in meta.source_notes


def test_extract_hooks_note_absent_when_no_hooks_file(tmp_path: Path) -> None:
    cand = FolderCandidate(path=tmp_path, folder_name="ш1 P", clean_title="P")

    meta = extract_metadata(cand)

    assert "hooks:present" not in meta.source_notes


def test_extract_thumbnail_absent_when_no_cover(tmp_path: Path) -> None:
    cand = FolderCandidate(path=tmp_path, folder_name="ш1 P", clean_title="P")

    meta = extract_metadata(cand)

    assert meta.thumbnail is None
    assert "thumbnail:final_cover" not in meta.source_notes


def test_extract_broken_json_is_ignored(tmp_path: Path) -> None:
    plan = tmp_path / "p_editing_plan.json"
    plan.write_text("{broken json", encoding="utf-8")
    cand = FolderCandidate(path=tmp_path, folder_name="ш1 P", clean_title="P", editing_plan=plan)

    meta = extract_metadata(cand)

    assert meta.description == ""
    assert meta.tags == []


def test_extract_scalar_json_is_ignored(tmp_path: Path) -> None:
    plan = _write_json(tmp_path / "p_editing_plan.json", 123)
    hashtags = tmp_path / "p_hashtags.txt"
    hashtags.write_text("#ok", encoding="utf-8")
    cand = FolderCandidate(
        path=tmp_path,
        folder_name="ш1 P",
        clean_title="P",
        editing_plan=plan,
        hashtags_txt=hashtags,
    )

    meta = extract_metadata(cand)

    assert meta.description == ""
    assert meta.tags == ["ok"]


def test_extract_with_missing_paths_is_empty(tmp_path: Path) -> None:
    cand = FolderCandidate(
        path=tmp_path,
        folder_name="ш1 P",
        clean_title="P",
        editing_plan=tmp_path / "missing_plan.json",
        final_aisie_plan=tmp_path / "missing_aisie.json",
        titles_txt=tmp_path / "missing_titles.txt",
        hashtags_txt=tmp_path / "missing_hashtags.txt",
    )

    meta = extract_metadata(cand)

    assert meta.description == ""
    assert meta.tags == []


def test_extract_media_short_note_when_probe_reports_short(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")
    monkeypatch.setattr(media_mod, "is_likely_short", lambda _p: True)
    cand = FolderCandidate(path=tmp_path, folder_name="ш1 P", clean_title="P", video_file=video)

    meta = extract_metadata(cand)

    assert "media:likely_short" in meta.source_notes


def test_extract_media_not_short_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")
    monkeypatch.setattr(media_mod, "is_likely_short", lambda _p: False)
    cand = FolderCandidate(path=tmp_path, folder_name="ш1 P", clean_title="P", video_file=video)

    meta = extract_metadata(cand)

    assert "media:not_short" in meta.source_notes


def test_extract_media_probe_exception_is_swallowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")

    def boom(_path: Path | str) -> bool:
        raise RuntimeError("probe exploded")

    monkeypatch.setattr(media_mod, "is_likely_short", boom)
    cand = FolderCandidate(path=tmp_path, folder_name="ш1 P", clean_title="P", video_file=video)

    meta = extract_metadata(cand)  # не должно бросить

    assert "media:likely_short" not in meta.source_notes
    assert "media:not_short" not in meta.source_notes


# --------------------------------------------------------------------------- #
# metadata_extractor: AI-заглушка
# --------------------------------------------------------------------------- #


class _SpyAI:
    def __init__(self) -> None:
        calls.append("init")

    def generate_description(self, topic: str) -> str:
        calls.append("description")
        return "AI описание"

    def generate_tags(self, topic: str) -> list[str]:
        calls.append("tags")
        return ["ai1", "ai2"]


calls: list[str] = []


def test_allow_ai_false_does_not_call_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls.clear()
    monkeypatch.setattr("aiyoutubehands.ai.AIEngine", _SpyAI)
    cand = FolderCandidate(path=tmp_path, folder_name="ш1 X", clean_title="X")

    meta = extract_metadata(cand)  # allow_ai=False по умолчанию

    assert calls == []
    assert meta.description == ""
    assert meta.tags == []


def test_allow_ai_true_fills_missing_description_and_tags(tmp_path: Path) -> None:
    cand = FolderCandidate(path=tmp_path, folder_name="ш9 T", clean_title="T")

    meta = extract_metadata(cand, allow_ai=True)  # локальная заглушка, без сети

    assert meta.description
    assert len(meta.tags) >= 2
    assert "description:ai" in meta.source_notes
    assert "tags:ai" in meta.source_notes


def test_allow_ai_true_skipped_when_data_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls.clear()
    monkeypatch.setattr("aiyoutubehands.ai.AIEngine", _SpyAI)
    titles = tmp_path / "p_titles.txt"
    titles.write_text("T\n\nДостаточно длинное описание для видео.", encoding="utf-8")
    hashtags = tmp_path / "p_hashtags.txt"
    hashtags.write_text("#a #b #c", encoding="utf-8")
    cand = FolderCandidate(
        path=tmp_path,
        folder_name="ш1 P",
        clean_title="P",
        titles_txt=titles,
        hashtags_txt=hashtags,
    )

    meta = extract_metadata(cand, allow_ai=True)

    assert calls == []
    assert "description:ai" not in meta.source_notes
    assert "tags:ai" not in meta.source_notes


def test_allow_ai_true_fills_only_missing_tags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls.clear()
    monkeypatch.setattr("aiyoutubehands.ai.AIEngine", _SpyAI)
    titles = tmp_path / "p_titles.txt"
    titles.write_text("T\n\nОписание из titles уже есть.", encoding="utf-8")
    hashtags = tmp_path / "p_hashtags.txt"
    hashtags.write_text("#only", encoding="utf-8")
    cand = FolderCandidate(
        path=tmp_path,
        folder_name="ш1 P",
        clean_title="P",
        titles_txt=titles,
        hashtags_txt=hashtags,
    )

    meta = extract_metadata(cand, allow_ai=True)

    assert meta.description == "Описание из titles уже есть."
    assert "description:ai" not in meta.source_notes
    assert "tags:ai" in meta.source_notes
    assert calls.count("description") == 0
    assert calls.count("tags") == 1
    assert meta.tags[0] == "only"


# --------------------------------------------------------------------------- #
# metadata_extractor: интеграция со scan_folder
# --------------------------------------------------------------------------- #


def test_extract_metadata_via_scan_integration(tmp_path: Path) -> None:
    root = tmp_path / "sm"
    root.mkdir()
    plan = {"clips": [{"description": "Описание из плана", "hashtags": ["тэг1", "тэг2"]}]}
    d = _make_folder(
        root,
        "ш1 Почему люди завидуют?",
        titles="Заголовок\n\nОписание из titles",
        hashtags="#shorts #мотивация",
        editing_plan=plan,
        hooks="Хук",
    )

    cand = scan_folder(d)
    meta = extract_metadata(cand)

    assert meta.title == "Почему люди завидуют?"
    assert meta.description == "Описание из плана"
    assert [t.lower() for t in meta.tags] == ["shorts", "мотивация"]
    assert meta.thumbnail is not None
    assert "hooks:present" in meta.source_notes
    # ffprobe в тестах отключён — локальная эвристика не должна ничего добавлять
    assert "media:likely_short" not in meta.source_notes
    assert "media:not_short" not in meta.source_notes


def test_extract_metadata_via_scan_with_final_aisie_plan(tmp_path: Path) -> None:
    root = tmp_path / "sm"
    root.mkdir()
    d = _make_folder(
        root,
        "ш2 Aisie",
        mp4=False,
        titles="T\n\nОписание из titles",
        final_aisie_plan={"clips": [{"description": "Описание из aisie"}]},
    )

    cand = scan_folder(d)
    meta = extract_metadata(cand)

    assert cand.final_aisie_plan is not None
    assert cand.editing_plan is None
    assert meta.description == "Описание из aisie"
    assert "description:final_aisie_plan" in meta.source_notes


# ---------------------------------------------------------------------------
# Нештатный JSON от ffprobe не должен ронять сопоставление папок
# ---------------------------------------------------------------------------


def test_duration_with_non_dict_format_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`format` не словарь → None, а не AttributeError.

    Регресс: `(data.get("format") or {}).get("duration")` падал с
    AttributeError на `{"format": "boom"}`, а matcher вызывает эту функцию
    без try/except — нештатный ответ ffprobe ломал весь разбор папок.
    """
    f = tmp_path / "v.mp4"
    f.write_bytes(b"x")
    monkeypatch.setattr(media_mod.shutil, "which", lambda _n: "/usr/bin/ffprobe")
    _set_run(monkeypatch, _FakeProc(stdout='{"format": "boom"}'))

    assert media_mod.probe_duration_seconds(f) is None


def test_duration_with_non_string_duration_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "v.mp4"
    f.write_bytes(b"x")
    monkeypatch.setattr(media_mod.shutil, "which", lambda _n: "/usr/bin/ffprobe")
    _set_run(monkeypatch, _FakeProc(stdout='{"format": {"duration": {"x": 1}}}'))

    assert media_mod.probe_duration_seconds(f) is None


def test_vertical_with_non_dict_stream_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Элемент streams не словарь → None, а не AttributeError."""
    f = tmp_path / "v.mp4"
    f.write_bytes(b"x")
    monkeypatch.setattr(media_mod.shutil, "which", lambda _n: "/usr/bin/ffprobe")
    _set_run(monkeypatch, _FakeProc(stdout='{"streams": ["boom"]}'))

    assert media_mod.probe_is_vertical(f) is None


def test_vertical_with_non_dict_data_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "v.mp4"
    f.write_bytes(b"x")
    monkeypatch.setattr(media_mod.shutil, "which", lambda _n: "/usr/bin/ffprobe")
    _set_run(monkeypatch, _FakeProc(stdout='["streams"]'))

    assert media_mod.probe_is_vertical(f) is None
