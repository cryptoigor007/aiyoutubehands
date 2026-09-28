"""Tests for configuration."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml

from aiyoutubehands.config import (
    AppConfig,
    ConfigError,
    get_config_dir,
    get_state_dir,
    load_config,
    load_config_optional,
    save_channel_id,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_get_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    d = get_config_dir()
    assert d == tmp_path / ".config" / "aiyoutubehands"


def test_get_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    d = get_state_dir()
    assert d == tmp_path / ".local" / "state" / "aiyoutubehands"


def test_load_config_from_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg_dir = tmp_path / ".config" / "aiyoutubehands"
    cfg_dir.mkdir(parents=True)
    cfg_file = cfg_dir / "config.yaml"
    data = {
        "channel": {"expected_channel_id": "UC_test123"},
        "auth": {"token_file": "~/.config/aiyoutubehands/token.age"},
        "quota": {"daily_limit": 5000},
        "ai": {"default_provider": "local", "allow_cloud": False},
        "logging": {"level": "DEBUG", "json_output": True},
        "calendar": {"db_path": "~/.local/state/aiyoutubehands/calendar.db"},
    }
    cfg_file.write_text(yaml.dump(data), encoding="utf-8")
    cfg = load_config()
    assert cfg.channel.expected_channel_id == "UC_test123"
    assert cfg.quota.daily_limit == 5000
    assert cfg.ai.default_provider == "local"
    assert cfg.logging.level == "DEBUG"


def test_load_config_missing_channel_id_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg_dir = tmp_path / ".config" / "aiyoutubehands"
    cfg_dir.mkdir(parents=True)
    cfg_file = cfg_dir / "config.yaml"
    cfg_file.write_text(yaml.dump({"channel": {}}), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config()


def test_app_config_defaults() -> None:
    cfg = AppConfig()
    assert cfg.quota.daily_limit == 10000
    assert cfg.ai.default_provider == "local"
    assert cfg.ai.allow_cloud is False
    assert cfg.logging.level == "INFO"


def test_load_config_optional_without_channel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg_dir = tmp_path / ".config" / "aiyoutubehands"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.yaml").write_text("logging:\n  level: INFO\n", encoding="utf-8")
    cfg = load_config_optional()
    assert cfg.logging.level == "INFO"
    assert cfg.channel is None


def test_default_paths_follow_xdg_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_home = tmp_path / "config-home"
    state_home = tmp_path / "state-home"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.setenv("XDG_STATE_HOME", str(state_home))
    cfg = load_config_optional()
    assert cfg.auth.token_file == str(config_home / "aiyoutubehands" / "token.age")
    assert cfg.auth.client_secrets_file == str(
        config_home / "aiyoutubehands" / "client_secrets.age"
    )
    assert cfg.calendar.db_path == str(state_home / "aiyoutubehands" / "calendar.db")


def test_save_channel_id_creates_private_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    path = save_channel_id("UC_channel")
    assert path.is_file()
    assert path.stat().st_mode & 0o777 == 0o600
    assert load_config().channel.expected_channel_id == "UC_channel"
