"""Дополнительные тесты инфраструктурных модулей (покрытие веток).

Файл намеренно изолирован: ничего в ``src/`` не меняется, сеть не используется.
``tests/conftest.py`` уже перенаправляет ``HOME`` и снимает ``XDG_*`` в песочницу.
"""

from __future__ import annotations

import builtins
import gc
import importlib
import importlib.metadata as metadata
import json
import runpy
import sys
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click
import pytest
import yaml

if TYPE_CHECKING:
    from collections.abc import Iterator

from aiyoutubehands.agent_rules import (
    BANNER,
    load_rules_text,
    print_safety_banner,
    rules_file_path,
)
from aiyoutubehands.calendar import Calendar, CalendarEntry
from aiyoutubehands.cli_errors import (
    _error_fields,
    exit_code_for_exception,
    format_error_lines,
    handle_cli_error,
)
from aiyoutubehands.config import (
    AppConfig,
    ConfigError,
    _expand,
    load_config,
    load_config_optional,
    save_channel_id,
)
from aiyoutubehands.exceptions import (
    EXIT_GENERIC,
    EXIT_OK,
    EXIT_USAGE,
    AppError,
    exit_code_for_error_code,
)
from aiyoutubehands.main import main


@pytest.fixture(autouse=True)
def _flush_leaked_sqlite() -> Iterator[None]:
    """Calendar/QuotaLedger не закрывают SQLite-соединения (это баг, см. отчёт).

    Слишком много «утекших» соединений из тестов календаря всплывают позже
    ResourceWarning'ами при ``gc.collect()`` в ``test_quota``. Собираем мусор
    сразу после каждого теста этого файла, чтобы не влиять на соседние тесты.
    """
    yield
    gc.collect()


# --------------------------------------------------------------------------- #
# exceptions.py
# --------------------------------------------------------------------------- #


def test_app_error_defaults_and_str() -> None:
    err = AppError("boom")
    assert err.code == "APP_ERROR"
    assert err.message == "boom"
    assert err.action == ""
    assert err.retryable is False
    assert err.exit_code == EXIT_GENERIC
    assert str(err) == "boom"


def test_app_error_custom_fields() -> None:
    err = AppError(
        "нет доступа",
        code="AUTH_REQUIRED",
        action="войдите заново",
        retryable=True,
        exit_code=10,
    )
    assert err.code == "AUTH_REQUIRED"
    assert err.message == "нет доступа"
    assert err.action == "войдите заново"
    assert err.retryable is True
    assert err.exit_code == 10


def test_exit_code_for_error_code_known_values() -> None:
    assert exit_code_for_error_code("CONFIG_ERROR") == 20
    assert exit_code_for_error_code("QUOTA_EXCEEDED") == 30
    assert exit_code_for_error_code("NETWORK_ERROR") == 40
    assert exit_code_for_error_code("NOT_FOUND") == 50
    assert exit_code_for_error_code("FORBIDDEN") == 60
    assert exit_code_for_error_code("CHANNEL_MISMATCH") == 71
    assert exit_code_for_error_code("UNSUPPORTED") == 80
    assert exit_code_for_error_code("CIRCUIT_OPEN") == 90
    assert exit_code_for_error_code("BAD_REQUEST") == EXIT_USAGE


# --------------------------------------------------------------------------- #
# cli_errors.py
# --------------------------------------------------------------------------- #


def test_error_fields_app_error_without_code_attribute() -> None:
    # code == "" заставляет _error_fields дойти до ветки isinstance(AppError).
    err = AppError("m", code="", action="act", retryable=True)
    assert _error_fields(err) == ("", "m", "act", True)


def test_error_fields_file_not_found() -> None:
    code, message, action, retryable = _error_fields(FileNotFoundError("нет файла"))
    assert code == "NOT_FOUND"
    assert message == "нет файла"
    assert action == "Проверьте путь к файлу"
    assert retryable is False


def test_error_fields_permission_denied() -> None:
    code, message, action, retryable = _error_fields(PermissionError("нет прав"))
    assert code == "FORBIDDEN"
    assert message == "нет прав"
    assert action == "Проверьте права доступа"
    assert retryable is False


def test_error_fields_unknown_exception_uses_app_error() -> None:
    code, message, action, retryable = _error_fields(RuntimeError("прочее"))
    assert code == "APP_ERROR"
    assert message == "прочее"
    assert action == ""
    assert retryable is False


def test_exit_code_for_exception_app_error() -> None:
    assert exit_code_for_exception(AppError("m", exit_code=7)) == 7


def test_exit_code_for_exception_value_error() -> None:
    # ValueError → "USAGE" через _error_fields, затем ветка code == "USAGE".
    assert exit_code_for_exception(ValueError("bad")) == EXIT_USAGE


def test_exit_code_for_exception_click_exception() -> None:
    assert exit_code_for_exception(click.ClickException("bad")) == EXIT_USAGE


def test_exit_code_for_exception_click_exit() -> None:
    assert exit_code_for_exception(click.exceptions.Exit(3)) == 3


def test_format_error_lines_without_action() -> None:
    assert format_error_lines(RuntimeError("x")) == ["ошибка [APP_ERROR]: x"]


def test_format_error_lines_retryable_and_action() -> None:
    lines = format_error_lines(AppError("m", action="сделай так", retryable=True))
    assert lines[0] == "ошибка [APP_ERROR]: m"
    assert "действие: сделай так" in lines
    assert "можно повторить: да" in lines


def test_handle_cli_error_custom_stream() -> None:
    """Ошибка пишется в переданный поток, а не в stderr Click."""
    err = StringIO()
    code = handle_cli_error(RuntimeError("boom"), err=err)
    assert code == EXIT_GENERIC
    written = err.getvalue()
    assert "APP_ERROR" in written
    assert "boom" in written


def test_handle_cli_error_click_exit() -> None:
    assert handle_cli_error(click.exceptions.Exit(5)) == 5


def test_handle_cli_error_abort(capsys: pytest.CaptureFixture[str]) -> None:
    code = handle_cli_error(click.Abort())
    assert code == EXIT_GENERIC
    assert "отменено" in capsys.readouterr().err


def test_handle_cli_error_click_exception(capsys: pytest.CaptureFixture[str]) -> None:
    code = handle_cli_error(click.ClickException("плохой ввод"))
    assert code == EXIT_USAGE
    assert "плохой ввод" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# logging.py
# --------------------------------------------------------------------------- #


def test_setup_logging_fallback_emits_json_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    import aiyoutubehands.logging as logmod

    monkeypatch.setattr(logmod, "_HAS_STRUCTLOG", False)
    stream = StringIO()
    logmod.setup_logging(level="DEBUG", json_output=False, stream=stream)

    log = logmod.get_logger()
    bound = log.bind(session="s1")
    assert bound is log

    log.info("info-event", a=1)
    log.warning("warn-event")
    log.error("err-event")
    log.debug("dbg-event")

    records = [json.loads(line) for line in stream.getvalue().strip().splitlines()]
    assert {r["event"] for r in records} == {"info-event", "warn-event", "err-event", "dbg-event"}
    assert {r["level"] for r in records} == {"info", "warning", "error", "debug"}
    assert all(r["correlation_id"] for r in records)
    assert records[0]["a"] == 1


def test_setup_logging_fallback_unknown_level(monkeypatch: pytest.MonkeyPatch) -> None:
    import logging as std_logging

    import aiyoutubehands.logging as logmod

    monkeypatch.setattr(logmod, "_HAS_STRUCTLOG", False)
    stream = StringIO()
    logmod.setup_logging(level="NOT-A-LEVEL", json_output=True, stream=stream)
    assert std_logging.getLogger().level == std_logging.INFO


def test_logging_import_error_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    import aiyoutubehands.logging as logmod

    real_import = builtins.__import__

    def fake_import(
        name: str,
        _globals: dict[str, Any] | None = None,
        _locals: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if name == "structlog":
            raise ImportError("structlog disabled for test")
        return real_import(name, _globals, _locals, fromlist, level)

    # Загружаем ИЗОЛИРОВАННУЮ копию модуля, чтобы не трогать живой
    # aiyoutubehands.logging (reload в процессе ломает correlation_id_var
    # для других тестов).
    monkeypatch.setattr(builtins, "__import__", fake_import)
    try:
        spec = importlib.util.spec_from_file_location("_ayh_logging_fallback_copy", logmod.__file__)
        assert spec is not None and spec.loader is not None
        isolated = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(isolated)
        assert isolated._HAS_STRUCTLOG is False
        assert isolated.structlog is None

        stream = StringIO()
        isolated.setup_logging(level="INFO", stream=stream)
        bound = isolated.get_logger("fallback")
        bound.info("hi", k=1)
        bound.warning("w")
        assert "hi" in stream.getvalue()
        assert "w" in stream.getvalue()
    finally:
        monkeypatch.undo()
    # реальный модуль не пострадал
    assert logmod._HAS_STRUCTLOG is True


# --------------------------------------------------------------------------- #
# config.py
# --------------------------------------------------------------------------- #


def test_load_config_default_path_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(ConfigError) as excinfo:
        load_config()
    assert excinfo.value.code == "CONFIG_MISSING_CHANNEL_ID"


def test_load_config_optional_default_path_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = load_config_optional()
    assert cfg.channel is None


def test_empty_channel_mapping_becomes_none() -> None:
    cfg = AppConfig.model_validate({"channel": {}})
    assert cfg.channel is None


def test_expand_plain_path_falls_back_to_expanduser() -> None:
    assert _expand("/tmp/some-file") == "/tmp/some-file"
    assert _expand("~/custom/file").startswith("/")


def test_load_config_explicit_missing_path(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as excinfo:
        load_config(tmp_path / "nope.yaml")
    assert excinfo.value.code == "CONFIG_MISSING_CHANNEL_ID"


def test_load_config_non_dict_yaml(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("- один\n- два\n", encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        load_config(path)
    assert excinfo.value.code == "CONFIG_MISSING_CHANNEL_ID"


def test_load_config_read_error(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_bytes(b"\xff\xfe\x00bad-utf8")
    with pytest.raises(ConfigError) as excinfo:
        load_config(path)
    assert excinfo.value.code == "CONFIG_READ_ERROR"
    assert excinfo.value.action == "Проверьте синтаксис YAML"


def test_load_config_invalid_schema(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    data = {
        "channel": {"expected_channel_id": "UC1"},
        "quota": {"daily_limit": -5},
    }
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        load_config(path)
    assert excinfo.value.code == "CONFIG_VALIDATION_ERROR"
    assert excinfo.value.action == "Исправьте config.yaml"


def test_load_config_optional_explicit_missing_path(tmp_path: Path) -> None:
    cfg = load_config_optional(tmp_path / "nope.yaml")
    assert cfg.channel is None


def test_load_config_optional_non_dict_yaml(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("42\n", encoding="utf-8")
    cfg = load_config_optional(path)
    assert cfg.channel is None


def test_load_config_optional_read_error(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(ConfigError) as excinfo:
        load_config_optional(path)
    assert excinfo.value.code == "CONFIG_READ_ERROR"


def test_load_config_optional_invalid_schema(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("quota:\n  daily_limit: -1\n", encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        load_config_optional(path)
    assert excinfo.value.code == "CONFIG_VALIDATION_ERROR"


def test_save_channel_id_rejects_bad_prefix(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as excinfo:
        save_channel_id("bad-id", path=tmp_path / "config.yaml")
    assert excinfo.value.code == "CONFIG_INVALID_CHANNEL_ID"


def test_save_channel_id_read_error(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(ConfigError) as excinfo:
        save_channel_id("UC123", path=path)
    assert excinfo.value.code == "CONFIG_READ_ERROR"


def test_save_channel_id_creates_missing_file(tmp_path: Path) -> None:
    path = tmp_path / "fresh.yaml"
    assert not path.exists()
    result = save_channel_id("UC_fresh", path=path)
    assert result.is_file()


def test_save_channel_id_existing_non_dict_yaml(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("42\n", encoding="utf-8")  # валидный YAML, но не mapping
    result = save_channel_id("UC_dict", path=path)
    assert result.is_file()
    cfg = load_config(path)
    assert cfg.channel is not None
    assert cfg.channel.expected_channel_id == "UC_dict"


def test_save_channel_id_updates_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("logging:\n  level: DEBUG\n", encoding="utf-8")
    result = save_channel_id("UC_new_channel", path=path)
    assert result == path
    cfg = load_config(path)
    assert cfg.channel is not None
    assert cfg.channel.expected_channel_id == "UC_new_channel"
    # существующая секция не потеряна
    assert cfg.logging.level == "DEBUG"


# --------------------------------------------------------------------------- #
# main.py
# --------------------------------------------------------------------------- #


class _FakeCLI:
    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    def main(self, *args: Any, **kwargs: Any) -> Any:
        raise self._exc


def test_main_system_exit_none(monkeypatch: pytest.MonkeyPatch) -> None:
    import aiyoutubehands.main as mainmod

    monkeypatch.setattr(mainmod, "cli", _FakeCLI(SystemExit(None)))
    assert mainmod.main(["anything"]) == EXIT_OK


def test_main_system_exit_with_int(monkeypatch: pytest.MonkeyPatch) -> None:
    import aiyoutubehands.main as mainmod

    monkeypatch.setattr(mainmod, "cli", _FakeCLI(SystemExit(3)))
    assert mainmod.main(["anything"]) == 3


def test_main_system_exit_with_string(monkeypatch: pytest.MonkeyPatch) -> None:
    import aiyoutubehands.main as mainmod

    monkeypatch.setattr(mainmod, "cli", _FakeCLI(SystemExit("boom")))
    assert mainmod.main(["anything"]) == 1


def test_main_system_exit_with_empty_string(monkeypatch: pytest.MonkeyPatch) -> None:
    import aiyoutubehands.main as mainmod

    monkeypatch.setattr(mainmod, "cli", _FakeCLI(SystemExit("")))
    assert mainmod.main(["anything"]) == EXIT_OK


def test_main_entrypoint_dunder_main(monkeypatch: pytest.MonkeyPatch) -> None:
    import aiyoutubehands.main as mainmod

    monkeypatch.setattr(sys, "argv", ["ayh", "version"])
    with pytest.raises(SystemExit) as excinfo:
        runpy.run_path(str(mainmod.__file__), run_name="__main__")
    assert excinfo.value.code == EXIT_OK


def test_main_maps_domain_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import aiyoutubehands.main as mainmod

    monkeypatch.setattr(mainmod, "cli", _FakeCLI(RuntimeError("domain failure")))
    assert mainmod.main(["anything"]) == EXIT_GENERIC


def test_main_direct_ok() -> None:
    assert main(["version"]) == EXIT_OK


# --------------------------------------------------------------------------- #
# __init__.py
# --------------------------------------------------------------------------- #


def test_version_from_file_finds_version_file() -> None:
    from aiyoutubehands import _version_from_file

    expected = (Path(__file__).resolve().parents[1] / "VERSION").read_text(encoding="utf-8").strip()
    assert _version_from_file() == expected


def test_version_from_file_fallback_when_no_version_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aiyoutubehands import _version_from_file

    monkeypatch.setattr(Path, "is_file", lambda *args, **kwargs: False)
    assert _version_from_file() == "0.1.0"


def test_package_version_fallback_on_package_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import aiyoutubehands as pkg

    def boom(name: str) -> str:
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(metadata, "version", boom)
    try:
        # Изолированная копия __init__.py: не перезагружаем реальный пакет,
        # иначе меняем его атрибуты для остальных тестов.
        spec = importlib.util.spec_from_file_location("_ayh_init_copy", pkg.__file__)
        assert spec is not None and spec.loader is not None
        isolated = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(isolated)
        assert isolated.__version__ == isolated._version_from_file()
        assert isolated.__version__
    finally:
        monkeypatch.undo()
    # реальный пакет не пострадал
    assert pkg.__version__


# --------------------------------------------------------------------------- #
# agent_rules.py
# --------------------------------------------------------------------------- #


def test_find_repo_root_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    import aiyoutubehands.agent_rules as rulesmod

    monkeypatch.setattr(rulesmod, "RULES_REL", Path("no-such-dir") / "MISSING.md")
    monkeypatch.setattr(
        Path,
        "is_file",
        lambda *args, **kwargs: False,
    )
    assert rulesmod.find_repo_root() is None


def test_rules_file_path_none_when_root_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    import aiyoutubehands.agent_rules as rulesmod

    monkeypatch.setattr(rulesmod, "find_repo_root", lambda: None)
    assert rules_file_path() is None


def test_load_rules_text_none_when_no_rules_path(monkeypatch: pytest.MonkeyPatch) -> None:
    import aiyoutubehands.agent_rules as rulesmod

    monkeypatch.setattr(rulesmod, "rules_file_path", lambda: None)
    assert load_rules_text() is None


def test_load_rules_text_oserror_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import aiyoutubehands.agent_rules as rulesmod

    directory = tmp_path / "not-a-file"
    directory.mkdir()
    monkeypatch.setattr(rulesmod, "rules_file_path", lambda: directory)
    assert load_rules_text() is None


def test_load_rules_text_success() -> None:
    text = load_rules_text()
    assert text is not None
    assert text.strip()


def test_print_safety_banner_with_echo() -> None:
    captured: list[str] = []
    print_safety_banner(echo=captured.append)
    assert captured[0] == BANNER
    assert any("Файл правил:" in line for line in captured)


def test_print_safety_banner_missing_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    import aiyoutubehands.agent_rules as rulesmod

    monkeypatch.setattr(rulesmod, "find_repo_root", lambda: None)
    captured: list[str] = []
    print_safety_banner(echo=captured.append)
    assert any("не найден" in line for line in captured)


# --------------------------------------------------------------------------- #
# calendar.py
# --------------------------------------------------------------------------- #


def test_add_rejects_empty_video_id(tmp_path: Path) -> None:
    cal = Calendar(tmp_path / "cal.db")
    with pytest.raises(ValueError):
        cal.add(CalendarEntry("   ", "T", "2026-10-01T00:00:00Z"))


def test_update_status_and_delete(tmp_path: Path) -> None:
    cal = Calendar(tmp_path / "cal.db")
    cal.add(CalendarEntry("v9", "Nine", "2026-10-09T00:00:00Z"))
    cal.update_status("v9", "published")
    updated = cal.get("v9")
    assert updated is not None
    assert updated.status == "published"
    cal.delete("v9")
    assert cal.get("v9") is None


def test_list_entries_filter_by_status(tmp_path: Path) -> None:
    cal = Calendar(tmp_path / "cal.db")
    cal.add(CalendarEntry("v1", "A", "2026-10-01T00:00:00Z", status="scheduled"))
    cal.add(CalendarEntry("v2", "B", "2026-10-02T00:00:00Z", status="published"))
    published = cal.list_entries("published")
    assert [e.video_id for e in published] == ["v2"]


def test_ascii_grid_other_month_and_bad_dates(tmp_path: Path) -> None:
    cal = Calendar(tmp_path / "cal.db")
    cal.add(CalendarEntry("other", "Other", "2026-09-15T00:00:00Z"))
    cal.add(CalendarEntry("bad", "Bad", "garbage"))
    cal.add(CalendarEntry("short", "Short", "2026"))
    grid = cal.ascii_grid(year=2026, month=10)
    assert "Окт 2026" in grid
    assert "Other" not in grid


def test_ascii_grid_day_without_title_falls_back_to_id(tmp_path: Path) -> None:
    cal = Calendar(tmp_path / "cal.db")
    cal.add(CalendarEntry("vid-only", "", "2026-10-05T12:00:00Z"))
    grid = cal.ascii_grid(year=2026, month=10)
    assert "vid-only" in grid


def test_sync_from_youtube_stub_upserts(tmp_path: Path) -> None:
    cal = Calendar(tmp_path / "cal.db")
    count = cal.sync_from_youtube_stub(
        [
            {
                "id": "a",
                "title": "A",
                "publish_at": "2026-10-01T00:00:00Z",
                "status": "scheduled",
            },
            {"id": "b", "title": "B"},
        ]
    )
    assert count == 2
    assert cal.get("a") is not None
    entry_b = cal.get("b")
    assert entry_b is not None
    assert entry_b.status == "scheduled"
    assert entry_b.publish_at == ""
