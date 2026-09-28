"""Tests for AI engine."""

from __future__ import annotations

from aiyoutubehands.ai import AIEngine, LocalStubProvider


def test_generate_title() -> None:
    eng = AIEngine(LocalStubProvider())
    t = eng.generate_title("Python CLI")
    assert len(t) > 5


def test_generate_tags() -> None:
    eng = AIEngine()
    tags = eng.generate_tags("youtube automation")
    assert isinstance(tags, list)
    assert len(tags) >= 1


def test_generate_script() -> None:
    eng = AIEngine()
    s = eng.generate_script("test topic")
    assert len(s) > 10


def test_thumbnail_prompt() -> None:
    eng = AIEngine()
    p = eng.generate_thumbnail_prompt("AI tools")
    assert len(p) > 5


def test_russian_title_keyword() -> None:
    from aiyoutubehands.ai import LocalStubProvider

    text = LocalStubProvider().complete("Сгенерируй заголовок про Python")
    assert "AI YouTube Hands" in text or len(text) > 5
