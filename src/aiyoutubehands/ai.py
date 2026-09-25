"""AI core and command orchestration (local-first)."""

from __future__ import annotations

from typing import Any, Protocol

from aiyoutubehands.logging import get_logger

log = get_logger(__name__)


class AIProvider(Protocol):
    def complete(self, prompt: str, **kwargs: Any) -> str: ...


class LocalStubProvider:
    """Deterministic local stub — no cloud calls."""

    def complete(self, prompt: str, **kwargs: Any) -> str:
        p = prompt.lower()
        if "title" in p or "заголов" in p:
            return "Как я сделал X за 10 минут | AI YouTube Hands"
        if "description" in p or "описан" in p:
            return "В этом видео разберём тему подробно.\n\nТаймкоды:\n0:00 Интро\n\n#youtube #ai"
        if "tags" in p or "тег" in p:
            return "youtube, ai, tutorial, automation, cli"
        if "script" in p or "сценари" in p:
            return "Привет! Сегодня мы поговорим о...\n\n1. Введение\n2. Основная часть\n3. Заключение"
        if "thumbnail" in p or "обложк" in p:
            return "Bright thumbnail: bold text 'AI YT', high contrast, face looking at camera"
        return f"[local-stub] Ответ на: {prompt[:80]}"


class AIEngine:
    def __init__(self, provider: AIProvider | None = None, allow_cloud: bool = False) -> None:
        self.provider = provider or LocalStubProvider()
        self.allow_cloud = allow_cloud

    def generate_title(self, topic: str) -> str:
        log.info("ai_generate_title", topic=topic[:50])
        return self.provider.complete(f"Generate a YouTube title for: {topic}")

    def generate_description(self, topic: str) -> str:
        return self.provider.complete(f"Generate a YouTube description for: {topic}")

    def generate_tags(self, topic: str) -> list[str]:
        raw = self.provider.complete(f"Generate tags for: {topic}")
        return [t.strip() for t in raw.replace(",", " ").split() if t.strip()]

    def generate_script(self, topic: str) -> str:
        return self.provider.complete(f"Generate a video script for: {topic}")

    def generate_thumbnail_prompt(self, topic: str) -> str:
        return self.provider.complete(f"Generate a thumbnail prompt for: {topic}")

    def summarize(self, text: str) -> str:
        return self.provider.complete(f"Summarize: {text[:2000]}")

    def reply_to_comment(self, comment: str) -> str:
        return self.provider.complete(f"Reply politely to this YouTube comment: {comment}")
