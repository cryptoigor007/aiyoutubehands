"""Configuration loading and validation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(Exception):
    """Configuration error with structured fields."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "CONFIG_ERROR",
        action: str = "Проверьте конфигурацию",
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.action = action
        self.retryable = retryable


class ChannelConfig(BaseModel):
    expected_channel_id: str = Field(..., min_length=1)


class AuthConfig(BaseModel):
    client_secrets_file: str = "~/.config/aiyoutubehands/client_secrets.json"
    token_file: str = "~/.config/aiyoutubehands/token.age"


class QuotaConfig(BaseModel):
    daily_limit: int = Field(default=10000, ge=0)
    force_quota: bool = False


class AIConfig(BaseModel):
    default_provider: str = "local"
    allow_cloud: bool = False
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    gemini_api_key: str | None = None


class LoggingConfig(BaseModel):
    level: str = "INFO"
    json_output: bool = True


class CalendarConfig(BaseModel):
    db_path: str = "~/.local/state/aiyoutubehands/calendar.db"


class AppConfig(BaseModel):
    channel: ChannelConfig | None = None
    auth: AuthConfig = Field(default_factory=AuthConfig)
    quota: QuotaConfig = Field(default_factory=QuotaConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    calendar: CalendarConfig = Field(default_factory=CalendarConfig)

    @field_validator("channel", mode="before")
    @classmethod
    def _empty_channel_to_none(cls, v: Any) -> Any:
        if v is None or v == {}:
            return None
        return v


def get_config_dir() -> Path:
    """Return ~/.config/aiyoutubehands (or $XDG_CONFIG_HOME)."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        base = Path(xdg)
    else:
        base = Path.home() / ".config"
    return base / "aiyoutubehands"


def get_state_dir() -> Path:
    """Return ~/.local/state/aiyoutubehands (or $XDG_STATE_HOME)."""
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        base = Path(xdg)
    else:
        base = Path.home() / ".local" / "state"
    return base / "aiyoutubehands"


def _expand(path: str) -> str:
    return str(Path(path).expanduser())


def load_config(path: Path | None = None) -> AppConfig:
    """Load configuration from YAML file.

    Raises ConfigError if required fields are missing or invalid.
    """
    if path is None:
        path = get_config_dir() / "config.yaml"

    data: dict[str, Any] = {}
    if path.is_file():
        try:
            raw = path.read_text(encoding="utf-8")
            loaded = yaml.safe_load(raw)
            if isinstance(loaded, dict):
                data = loaded
        except Exception as exc:
            raise ConfigError(
                f"Не удалось прочитать конфиг {path}: {exc}",
                code="CONFIG_READ_ERROR",
                action="Проверьте синтаксис YAML",
            ) from exc

    try:
        cfg = AppConfig.model_validate(data)
    except Exception as exc:
        raise ConfigError(
            f"Невалидный конфиг: {exc}",
            code="CONFIG_VALIDATION_ERROR",
            action="Исправьте config.yaml",
        ) from exc

    if cfg.channel is None or not cfg.channel.expected_channel_id:
        raise ConfigError(
            "Отсутствует channel.expected_channel_id",
            code="CONFIG_MISSING_CHANNEL_ID",
            action="Укажите expected_channel_id в config.yaml",
        )

    # Expand user paths
    cfg.auth.client_secrets_file = _expand(cfg.auth.client_secrets_file)
    cfg.auth.token_file = _expand(cfg.auth.token_file)
    cfg.calendar.db_path = _expand(cfg.calendar.db_path)

    return cfg
