"""Сканер не должен путать файлы-спутники AppleDouble (``._*``) с настоящими.

На exFAT/сетевых дисках macOS создаёт рядом с каждым файлом служебный
``._имя``. Он сортируется раньше настоящего (``.`` < ``Ш``), поэтому
``_find_first`` выбирал его. Итог: в описание и теги попадал бинарный мусор,
а вместо обложки уходил 4-килобайтный ресурсный форк.
"""

from __future__ import annotations

import json

from aiyoutubehands.shorts_maker.folder_scanner import scan_folder
from aiyoutubehands.shorts_maker.metadata_extractor import extract_metadata

PREFIX = "ш64 Почему люди боятся выделяться из толпы"
APPLEDOUBLE = "\x00\x05\x16\x07ATTRcom.apple.provenance"


def _make_folder(tmp_path, *, with_appledouble: bool):
    folder = tmp_path / PREFIX
    folder.mkdir()

    (folder / f"{PREFIX}_final.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")
    (folder / f"{PREFIX}_final_cover.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"x" * 500)
    (folder / f"{PREFIX}_titles.txt").write_text(
        "Заголовок: Почему ты боишься выделяться?\nОписание: Настоящее описание ролика.\n",
        encoding="utf-8",
    )
    (folder / f"{PREFIX}_hashtags.txt").write_text(
        "#психология #уверенность #толпа\n", encoding="utf-8"
    )
    (folder / f"{PREFIX}_editing_plan.json").write_text(
        json.dumps({"clips": [{"description": "Описание из плана монтажа."}]}, ensure_ascii=False),
        encoding="utf-8",
    )

    if with_appledouble:
        for name in (
            "_final.mp4",
            "_final_cover.jpg",
            "_titles.txt",
            "_hashtags.txt",
            "_editing_plan.json",
        ):
            (folder / f"._{PREFIX}{name}").write_bytes(APPLEDOUBLE.encode("utf-8"))
    return folder


def test_scanner_ignores_appledouble_files(tmp_path) -> None:
    """Сканер обязан выбрать настоящие файлы, а не ``._`` спутники."""
    folder = _make_folder(tmp_path, with_appledouble=True)

    cand = scan_folder(folder)

    assert cand.video_file is not None
    assert cand.video_file.name == f"{PREFIX}_final.mp4", cand.video_file.name
    assert cand.cover is not None
    assert cand.cover.name == f"{PREFIX}_final_cover.jpg", cand.cover.name
    assert cand.titles_txt is not None
    assert cand.titles_txt.name == f"{PREFIX}_titles.txt", cand.titles_txt.name
    assert cand.hashtags_txt is not None
    assert cand.hashtags_txt.name == f"{PREFIX}_hashtags.txt", cand.hashtags_txt.name
    assert cand.editing_plan is not None
    assert cand.editing_plan.name == f"{PREFIX}_editing_plan.json", cand.editing_plan.name


def test_metadata_is_clean_with_appledouble_present(tmp_path) -> None:
    """Описание, теги и обложка не должны содержать бинарный мусор."""
    folder = _make_folder(tmp_path, with_appledouble=True)

    meta = extract_metadata(scan_folder(folder))

    assert meta.description == "Описание из плана монтажа.", repr(meta.description)
    assert meta.tags == ["психология", "уверенность", "толпа"], meta.tags
    assert meta.thumbnail is not None
    assert meta.thumbnail.name == f"{PREFIX}_final_cover.jpg"
    for value in (meta.title, meta.description, *meta.tags):
        assert "ATTR" not in value
        assert "\x00" not in value


def test_scanner_still_works_without_appledouble(tmp_path) -> None:
    """Обычный диск (APFS) — поведение не изменилось."""
    folder = _make_folder(tmp_path, with_appledouble=False)

    cand = scan_folder(folder)

    assert cand.video_file is not None
    assert cand.video_file.name == f"{PREFIX}_final.mp4"
    assert cand.cover is not None
    assert cand.cover.name == f"{PREFIX}_final_cover.jpg"
