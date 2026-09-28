"""Paths and banner for mandatory agent safety rules."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

# Relative to repository root (parent of src/)
RULES_REL = Path("docs") / "AGENT_PROMPT_PROCESS.md"
AGENTS_REL = Path("AGENTS.md")

BANNER = """\
╔══════════════════════════════════════════════════════════════════════╗
║  ПРАВИЛА БЕЗОПАСНОСТИ ayh (обязательны для человека и AI-агента)    ║
║  Прочитай: docs/AGENT_PROMPT_PROCESS.md  и  AGENTS.md                 ║
║  • Не вредить пользователю, каналу, компьютеру                        ║
║  • Не delete / insert видео; не трогать оформленное и с просмотрами   ║
║  • apply: только после плана и фразы с хэшем (ДД.ММ.ГГГГ #<хэш>)       ║
║  • При сомнении — СТОП, не «улучшать на глаз»                         ║
╚══════════════════════════════════════════════════════════════════════╝"""


def find_repo_root() -> Path | None:
    """Walk up from this file to find repo root containing docs/AGENT_PROMPT_PROCESS.md."""
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        candidate = parent / RULES_REL
        if candidate.is_file():
            return parent
    return None


def rules_file_path() -> Path | None:
    root = find_repo_root()
    if root is None:
        return None
    path = root / RULES_REL
    return path if path.is_file() else None


def load_rules_text() -> str | None:
    path = rules_file_path()
    if path is None:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def print_safety_banner(*, echo: Callable[[str], None] | None = None) -> None:
    """Print safety banner to stdout (or click.echo if provided)."""
    out = echo if echo is not None else print
    out(BANNER)
    path = rules_file_path()
    if path is not None:
        out(f"Файл правил: {path}")
    else:
        out(
            "Файл правил: docs/AGENT_PROMPT_PROCESS.md "
            "(не найден рядом с установкой — откройте в репозитории)"
        )
