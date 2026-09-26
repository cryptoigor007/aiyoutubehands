"""Structured logging setup (structlog + correlation_id) with stdlib fallback."""

from __future__ import annotations

import json
import logging
import sys
import uuid
from contextvars import ContextVar
from typing import Any, TextIO

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")

_HAS_STRUCTLOG = False
try:
    import structlog

    _HAS_STRUCTLOG = True
except ImportError:
    structlog = None  # type: ignore[assignment]


def _new_correlation_id() -> str:
    return str(uuid.uuid4())


def _add_correlation_id(
    logger: logging.Logger, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    cid = correlation_id_var.get()
    if not cid:
        cid = _new_correlation_id()
        correlation_id_var.set(cid)
    event_dict["correlation_id"] = cid
    return event_dict


class _FallbackLogger:
    """Minimal logger when structlog is unavailable."""

    def __init__(self, name: str) -> None:
        self._log = logging.getLogger(name)

    def bind(self, **kwargs: Any) -> _FallbackLogger:
        return self

    def info(self, event: str, **kwargs: Any) -> None:
        self._emit("info", event, kwargs)

    def warning(self, event: str, **kwargs: Any) -> None:
        self._emit("warning", event, kwargs)

    def error(self, event: str, **kwargs: Any) -> None:
        self._emit("error", event, kwargs)

    def debug(self, event: str, **kwargs: Any) -> None:
        self._emit("debug", event, kwargs)

    def _emit(self, level: str, event: str, kwargs: dict[str, Any]) -> None:
        cid = correlation_id_var.get() or _new_correlation_id()
        payload = {"event": event, "level": level, "correlation_id": cid, **kwargs}
        getattr(self._log, level)(json.dumps(payload, ensure_ascii=False))


def setup_logging(
    *,
    level: str = "INFO",
    json_output: bool = True,
    stream: TextIO | None = None,
) -> None:
    if stream is None:
        stream = sys.stderr
    log_level = getattr(logging, level.upper(), logging.INFO)

    if not _HAS_STRUCTLOG:
        root = logging.getLogger()
        root.handlers.clear()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(message)s"))
        root.addHandler(handler)
        root.setLevel(log_level)
        return

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        _add_correlation_id,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    renderer: Any = (
        structlog.processors.JSONRenderer(ensure_ascii=False)
        if json_output
        else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=shared_processors
        + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )
    handler = logging.StreamHandler(stream)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> Any:
    if _HAS_STRUCTLOG:
        return structlog.get_logger(name)
    return _FallbackLogger(name or "ayh")
