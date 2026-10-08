"""Domain errors for community posts automation."""

from __future__ import annotations

from aiyoutubehands.exceptions import EXIT_GENERIC, EXIT_UNSUPPORTED, AppError


class PostsError(AppError):
    """Base error for the posts subsystem."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "POSTS_ERROR",
        action: str = "",
        retryable: bool = False,
        exit_code: int = EXIT_GENERIC,
    ) -> None:
        super().__init__(
            message,
            code=code,
            action=action,
            retryable=retryable,
            exit_code=exit_code,
        )


class SafariNotAvailableError(PostsError):
    """Running on non-macOS or Safari/osascript unavailable."""

    def __init__(self, message: str = "Safari automation доступна только на macOS") -> None:
        super().__init__(
            message,
            code="SAFARI_UNAVAILABLE",
            action="Запустите команду на macOS с Safari и разрешением Apple Events",
            retryable=False,
            exit_code=EXIT_UNSUPPORTED,
        )


class ElementTimeoutError(PostsError):
    """DOM element did not appear within the timeout."""

    def __init__(self, selector: str, timeout_s: float) -> None:
        super().__init__(
            f"Элемент не появился за {timeout_s:.1f} с: {selector}",
            code="ELEMENT_TIMEOUT",
            action="Убедитесь, что диалог создания записи открыт и страница загружена",
            retryable=True,
        )


class PublishRejectedError(PostsError):
    """YouTube returned «Не удалось опубликовать запись»."""

    def __init__(self, detail: str = "") -> None:
        msg = "Сервер отклонил публикацию записи"
        if detail:
            msg = f"{msg}: {detail}"
        super().__init__(
            msg,
            code="PUBLISH_REJECTED",
            action="Проверьте текст/картинку и попробуйте вручную в Studio",
            retryable=False,
        )


class ImageAttachFailedError(PostsError):
    """Image could not be attached; post must not be published without it."""

    def __init__(self, reason: str) -> None:
        super().__init__(
            f"Не удалось прикрепить картинку: {reason}",
            code="IMAGE_ATTACH_FAILED",
            action=(
                "Либо снимите HAR ручного выбора файла, либо включите Accessibility "
                "для нативного пикера (System Preferences → Privacy → Accessibility)"
            ),
            retryable=False,
        )


class AccessibilityDeniedError(PostsError):
    """System Events / Accessibility permission missing."""

    def __init__(self) -> None:
        super().__init__(
            "Нет разрешения Accessibility для управления нативным диалогом файла",
            code="ACCESSIBILITY_DENIED",
            action=(
                "Системные настройки → Конфиденциальность и безопасность → Универсальный доступ: "
                "добавьте Terminal / ваш терминал / Python"
            ),
            retryable=False,
        )
