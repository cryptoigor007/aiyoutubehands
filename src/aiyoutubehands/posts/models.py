"""Payload and validation for community posts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from aiyoutubehands.exceptions import EXIT_USAGE, AppError

# Limits aligned with YouTube Studio community post rules (verified 2026)
MAX_TEXT_CHARS = 5000
ALLOWED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
MAX_IMAGE_BYTES = 16 * 1024 * 1024  # 16 MiB hard limit from Studio
MAX_IMAGES_PER_POST = 10  # carousel; current CLI supports 1 image only
RECOMMENDED_IMAGE_SIDE_PX = (1080, 1200)  # inclusive range for square side
RECOMMENDED_ASPECT = "1:1 (квадрат)"

IMAGE_REQUIREMENTS_RU = (
    "Требования к картинке для «Записи» (вкладка Сообщество):\n"
    "  • Соотношение сторон: рекомендуется 1:1 (квадрат). "
    "Иначе в ленте кадрируется под квадрат.\n"
    "  • Разрешение: оптимально 1080×1080 … 1200×1200 px.\n"
    "  • Форматы: JPG, PNG, GIF (в т.ч. анимированный), WEBP.\n"
    "  • Макс. размер файла: 16 МБ.\n"
    "  • В одну запись — до 10 изображений (карусель); "
    "текущая команда принимает одно.\n"
    "  • Опросы с картинками: 1:1, до 4 вариантов, подпись ≤36 символов "
    "(пока не поддерживается CLI)."
)


class PostValidationError(AppError):
    """Invalid text file or image for a community post."""

    def __init__(self, message: str, *, action: str = "Проверьте входные файлы") -> None:
        super().__init__(
            message,
            code="POST_VALIDATION",
            action=action,
            retryable=False,
            exit_code=EXIT_USAGE,
        )


def validate_text_file(path: Path | str) -> str:
    """Read and validate a UTF-8 text file for the post body.

    Returns the stripped text.  Raises ``PostValidationError`` on problems.
    """
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise PostValidationError(f"Файл текста не найден: {p}")
    try:
        raw = p.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise PostValidationError(
            f"Файл текста не в UTF-8: {p}",
            action="Сохраните файл в UTF-8",
        ) from exc
    text = raw.strip()
    if not text:
        raise PostValidationError("Текст поста пустой")
    if len(text) > MAX_TEXT_CHARS:
        raise PostValidationError(
            f"Текст слишком длинный ({len(text)} символов, лимит {MAX_TEXT_CHARS})",
        )
    return text


def validate_image_path(path: Path | str | None) -> Path | None:
    """Validate optional image path.  Returns resolved Path or None.

    Enforces format and 16 MiB size limit.  Aspect ratio / resolution are
    recommendations only (documented in dry-run and docs/POSTS.md); we do not
    require Pillow and do not reject non-square images.
    """
    if path is None:
        return None
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise PostValidationError(f"Файл картинки не найден: {p}")
    suffix = p.suffix.lower()
    if suffix not in ALLOWED_IMAGE_SUFFIXES:
        raise PostValidationError(
            f"Неподдерживаемый формат картинки: {suffix}. "
            f"Допустимы: {', '.join(sorted(ALLOWED_IMAGE_SUFFIXES))}",
            action="Используйте JPG, PNG, GIF или WEBP",
        )
    size = p.stat().st_size
    if size == 0:
        raise PostValidationError(f"Файл картинки пустой: {p}")
    if size > MAX_IMAGE_BYTES:
        raise PostValidationError(
            f"Картинка слишком большая ({size} байт, лимит {MAX_IMAGE_BYTES} / 16 МБ)",
            action="Уменьшите файл до ≤16 МБ",
        )
    return p


@dataclass(frozen=True, slots=True)
class PostPayload:
    """Validated payload ready for dry-run or real publish."""

    text: str
    image: Path | None = None
    channel_id: str = ""

    @classmethod
    def from_files(
        cls,
        text_file: Path | str,
        image: Path | str | None = None,
        *,
        channel_id: str = "",
    ) -> PostPayload:
        text = validate_text_file(text_file)
        img = validate_image_path(image)
        return cls(text=text, image=img, channel_id=channel_id)

    def posts_url(self) -> str:
        """URL that opens the create-post dialog for the channel."""
        if not self.channel_id:
            raise PostValidationError(
                "channel_id не задан",
                action="Укажите expected_channel_id в config/local.yaml",
            )
        return (
            f"https://www.youtube.com/channel/{self.channel_id}/posts"
            f"?show_create_dialog=1"
        )
