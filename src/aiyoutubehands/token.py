"""OAuth2 token management with encryption, rotation, audit and health."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from aiyoutubehands.logging import get_logger

log = get_logger(__name__)


class TokenError(Exception):
    """Token-related error."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "TOKEN_ERROR",
        action: str = "Проверьте токен / авторизацию",
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.action = action
        self.retryable = retryable


@dataclass
class TokenData:
    access_token: str
    refresh_token: str = ""
    expires_at: int = 0  # unix timestamp
    token_type: str = "Bearer"
    scopes: list[str] = field(default_factory=list)

    def is_expired(self, skew: int = 60) -> bool:
        if self.expires_at <= 0:
            return True
        return time.time() >= (self.expires_at - skew)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TokenData:
        return cls(
            access_token=str(d.get("access_token", "")),
            refresh_token=str(d.get("refresh_token", "")),
            expires_at=int(d.get("expires_at", 0)),
            token_type=str(d.get("token_type", "Bearer")),
            scopes=list(d.get("scopes") or []),
        )


def encrypt_bytes(plaintext: bytes, key: bytes) -> bytes:
    """AES-256-GCM encrypt. key must be 32 bytes."""
    if len(key) != 32:
        raise TokenError("Ключ шифрования должен быть 32 байта", code="TOKEN_BAD_KEY")
    aes = AESGCM(key)
    nonce = os.urandom(12)
    ct = aes.encrypt(nonce, plaintext, None)
    return nonce + ct


def decrypt_bytes(blob: bytes, key: bytes) -> bytes:
    """AES-256-GCM decrypt."""
    if len(key) != 32:
        raise TokenError("Ключ шифрования должен быть 32 байта", code="TOKEN_BAD_KEY")
    if len(blob) < 13:
        raise TokenError("Повреждённый токен", code="TOKEN_CORRUPT")
    nonce, ct = blob[:12], blob[12:]
    aes = AESGCM(key)
    try:
        return aes.decrypt(nonce, ct, None)
    except Exception as exc:
        raise TokenError(
            "Не удалось расшифровать токен (неверный ключ или повреждение)",
            code="TOKEN_DECRYPT_FAILED",
            action="Проверьте ключ / файл токена",
        ) from exc


def derive_key_from_passphrase(passphrase: str, salt: bytes | None = None) -> tuple[bytes, bytes]:
    """Derive 32-byte key via scrypt. Returns (key, salt)."""
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

    if salt is None:
        salt = os.urandom(16)
    kdf = Scrypt(salt=salt, length=32, n=2**14, r=8, p=1)
    key = kdf.derive(passphrase.encode("utf-8"))
    return key, salt


class TokenStore:
    """Encrypted token storage + audit + health."""

    def __init__(
        self,
        path: Path | str,
        key: bytes,
        audit_path: Path | str | None = None,
    ) -> None:
        self.path = Path(path)
        self.key = key
        self.audit_path = Path(audit_path) if audit_path else self.path.with_suffix(".audit.jsonl")

    def save(self, data: TokenData) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(data.to_dict(), ensure_ascii=False).encode("utf-8")
        blob = encrypt_bytes(raw, self.key)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_bytes(blob)
        tmp.chmod(0o600)
        tmp.replace(self.path)
        self.path.chmod(0o600)
        self.audit("save", detail=f"expires_at={data.expires_at}")
        log.info("token_saved", path=str(self.path))

    def load(self) -> TokenData:
        if not self.path.is_file():
            raise TokenError(
                f"Файл токена не найден: {self.path}",
                code="TOKEN_NOT_FOUND",
                action="Выполните авторизацию (ayh auth login)",
            )
        blob = self.path.read_bytes()
        raw = decrypt_bytes(blob, self.key)
        try:
            d = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise TokenError("Повреждённый JSON токена", code="TOKEN_CORRUPT") from exc
        return TokenData.from_dict(d)

    def health(self) -> dict[str, Any]:
        try:
            data = self.load()
            return {
                "ok": True,
                "has_access": bool(data.access_token),
                "has_refresh": bool(data.refresh_token),
                "expired": data.is_expired(),
                "expires_at": data.expires_at,
                "scopes": data.scopes,
            }
        except TokenError as e:
            return {"ok": False, "error": e.code, "message": e.message}

    def audit(self, action: str, detail: str = "") -> None:
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": int(time.time()),
            "action": action,
            "detail": detail,
        }
        with self.audit_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        try:
            self.audit_path.chmod(0o600)
        except OSError:
            pass

    def rotate_access(self, new_access: str, expires_at: int) -> TokenData:
        """Update access token (after refresh)."""
        data = self.load()
        data.access_token = new_access
        data.expires_at = expires_at
        self.save(data)
        self.audit("rotate", detail="access_token refreshed")
        return data
