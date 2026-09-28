"""OAuth2 token management with encryption, rotation, audit and health.

Encryption: AES-256-GCM. On-disk format is versioned (magic AYH1).
Passphrase mode uses scrypt (salt stored in-file). Raw 32-byte key mode
remains for tests and advanced use.

Full Mozilla age CLI interop is not implemented yet; blob is application-specific.
"""

from __future__ import annotations

import contextlib
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from aiyoutubehands.logging import get_logger

log = get_logger(__name__)

BLOB_MAGIC = b"AYH1"
BLOB_MODE_RAW = 0
BLOB_MODE_PASSPHRASE = 1  # legacy: scrypt N=2**14
BLOB_MODE_PASSPHRASE_V2 = 2  # scrypt N=2**17
SALT_LEN = 16

# OWASP: scrypt N=2**17, r=8, p=1 для паролей.
SCRYPT_N = 2**17
SCRYPT_N_LEGACY = 2**14


def _ensure_private_dir(path: Path) -> None:
    """Создать каталог для секретов с правами 0700 (не 0755 по умолчанию)."""
    path.mkdir(parents=True, exist_ok=True, mode=0o700)


def _write_private(path: Path, blob: bytes) -> None:
    """Атомарно записать файл, создавая его сразу с правами 0600.

    Раньше файл создавался с обычными правами и только потом сужался через
    chmod — между записью и chmod секрет был доступен на чтение.
    """
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, blob)
    finally:
        os.close(fd)
    os.replace(tmp, path)


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
    """AES-256-GCM encrypt. key must be 32 bytes. Returns nonce + ciphertext."""
    if len(key) != 32:
        raise TokenError("Ключ шифрования должен быть 32 байта", code="TOKEN_BAD_KEY")
    aes = AESGCM(key)
    nonce = os.urandom(12)
    ct = aes.encrypt(nonce, plaintext, None)
    return nonce + ct


def decrypt_bytes(blob: bytes, key: bytes) -> bytes:
    """AES-256-GCM decrypt. blob is nonce + ciphertext."""
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


def derive_key_from_passphrase(
    passphrase: str, salt: bytes | None = None, *, n: int = SCRYPT_N
) -> tuple[bytes, bytes]:
    """Derive 32-byte key via scrypt. Returns (key, salt).

    ``n`` выбирается вызывающим: новые файлы — SCRYPT_N (2**17), старые
    блобы (mode 1) читаются с SCRYPT_N_LEGACY (2**14), иначе уже существующие
    token.age / client_secrets.age стали бы нечитаемыми.
    """
    if salt is None:
        salt = os.urandom(SALT_LEN)
    if len(salt) != SALT_LEN:
        raise TokenError("Неверная длина salt", code="TOKEN_BAD_SALT")
    kdf = Scrypt(salt=salt, length=32, n=n, r=8, p=1)
    key = kdf.derive(passphrase.encode("utf-8"))
    return key, salt


def pack_blob(payload: bytes, *, mode: int, salt: bytes | None = None) -> bytes:
    """Pack versioned on-disk blob."""
    if mode == BLOB_MODE_RAW:
        return BLOB_MAGIC + bytes([mode]) + payload
    if mode in (BLOB_MODE_PASSPHRASE, BLOB_MODE_PASSPHRASE_V2):
        if salt is None or len(salt) != SALT_LEN:
            raise TokenError("Для passphrase-режима нужен salt", code="TOKEN_BAD_SALT")
        return BLOB_MAGIC + bytes([mode]) + salt + payload
    raise TokenError(f"Неизвестный mode={mode}", code="TOKEN_BAD_MODE")


def unpack_blob(blob: bytes) -> tuple[int, bytes | None, bytes]:
    """Unpack versioned blob. Returns (mode, salt|None, payload).

    Legacy files without magic are treated as raw payload (mode RAW, no salt).
    """
    if blob.startswith(BLOB_MAGIC) and len(blob) >= 6:
        mode = blob[4]
        rest = blob[5:]
        if mode == BLOB_MODE_RAW:
            return mode, None, rest
        if mode in (BLOB_MODE_PASSPHRASE, BLOB_MODE_PASSPHRASE_V2):
            if len(rest) < SALT_LEN + 13:
                raise TokenError("Повреждённый токен", code="TOKEN_CORRUPT")
            return mode, rest[:SALT_LEN], rest[SALT_LEN:]
        raise TokenError(f"Неизвестный mode={mode}", code="TOKEN_BAD_MODE")
    # legacy: pure nonce+ct
    return BLOB_MODE_RAW, None, blob


def _scrypt_n_for_mode(mode: int) -> int:
    return SCRYPT_N if mode == BLOB_MODE_PASSPHRASE_V2 else SCRYPT_N_LEGACY


class TokenStore:
    """Encrypted token storage + audit + health."""

    def __init__(
        self,
        path: Path | str,
        key: bytes | None = None,
        *,
        passphrase: str | None = None,
        audit_path: Path | str | None = None,
    ) -> None:
        if key is None and passphrase is None:
            raise TokenError(
                "Нужен key или passphrase",
                code="TOKEN_BAD_KEY",
                action="Передайте 32-байтовый ключ или passphrase",
            )
        if key is not None and len(key) != 32:
            raise TokenError("Ключ шифрования должен быть 32 байта", code="TOKEN_BAD_KEY")
        self.path = Path(path)
        self._key = key
        self._passphrase = passphrase
        self.audit_path = Path(audit_path) if audit_path else self.path.with_suffix(".audit.jsonl")

    def _resolve_key(
        self, salt: bytes | None = None, *, n: int = SCRYPT_N
    ) -> tuple[bytes, bytes | None]:
        if self._passphrase is not None:
            key, used_salt = derive_key_from_passphrase(self._passphrase, salt, n=n)
            return key, used_salt
        if self._key is None:
            raise TokenError(
                "Не задан ни ключ, ни passphrase",
                code="TOKEN_NO_KEY",
                action="Передайте ключ или passphrase",
            )
        return self._key, None

    def save(self, data: TokenData) -> None:
        _ensure_private_dir(self.path.parent)
        raw = json.dumps(data.to_dict(), ensure_ascii=False).encode("utf-8")
        if self._passphrase is not None:
            key, salt = self._resolve_key(salt=None, n=SCRYPT_N)
            payload = encrypt_bytes(raw, key)
            blob = pack_blob(payload, mode=BLOB_MODE_PASSPHRASE_V2, salt=salt)
        else:
            key, _ = self._resolve_key()
            payload = encrypt_bytes(raw, key)
            blob = pack_blob(payload, mode=BLOB_MODE_RAW)
        _write_private(self.path, blob)
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
        mode, salt, payload = unpack_blob(blob)
        if mode in (BLOB_MODE_PASSPHRASE, BLOB_MODE_PASSPHRASE_V2):
            if self._passphrase is None:
                raise TokenError(
                    "Токен защищён passphrase, ключ не подходит",
                    code="TOKEN_BAD_KEY",
                    action="Передайте тот же passphrase",
                )
            key, _ = derive_key_from_passphrase(self._passphrase, salt, n=_scrypt_n_for_mode(mode))
        else:
            if self._key is None:
                # allow passphrase store to open raw only if key derived wrongly — reject
                raise TokenError(
                    "Токен в raw-режиме, нужен 32-байтовый ключ",
                    code="TOKEN_BAD_KEY",
                )
            key = self._key
        raw = decrypt_bytes(payload, key)
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
        with contextlib.suppress(OSError):
            self.audit_path.chmod(0o600)

    def rotate_access(self, new_access: str, expires_at: int) -> TokenData:
        """Update access token (after refresh)."""
        data = self.load()
        data.access_token = new_access
        data.expires_at = expires_at
        self.save(data)
        self.audit("rotate", detail="access_token refreshed")
        return data


class EncryptedJsonStore:
    """Passphrase-encrypted JSON storage for OAuth client configuration.

    OAuth desktop client metadata is not treated as an application secret by
    Google, but keeping it encrypted prevents it from becoming another
    readable credential file on the user's disk.
    """

    def __init__(self, path: Path | str, *, passphrase: str) -> None:
        if not passphrase:
            raise TokenError("Нужен пароль локального хранилища", code="TOKEN_BAD_KEY")
        self.path = Path(path)
        self._passphrase = passphrase

    def save(self, data: dict[str, Any]) -> None:
        _ensure_private_dir(self.path.parent)
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        key, salt = derive_key_from_passphrase(self._passphrase, n=SCRYPT_N)
        payload = encrypt_bytes(raw, key)
        _write_private(self.path, pack_blob(payload, mode=BLOB_MODE_PASSPHRASE_V2, salt=salt))

    def load(self) -> dict[str, Any]:
        if not self.path.is_file():
            raise TokenError(
                f"Зашифрованный файл OAuth-клиента не найден: {self.path}",
                code="CLIENT_SECRETS_MISSING",
                action="Импортируйте JSON: ayh auth import-client-secrets --source <файл>",
            )
        mode, salt, payload = unpack_blob(self.path.read_bytes())
        if mode not in (BLOB_MODE_PASSPHRASE, BLOB_MODE_PASSPHRASE_V2) or salt is None:
            raise TokenError(
                "Файл OAuth-клиента должен быть зашифрован паролем",
                code="CLIENT_SECRETS_UNENCRYPTED",
            )
        key, _ = derive_key_from_passphrase(self._passphrase, salt, n=_scrypt_n_for_mode(mode))
        raw = decrypt_bytes(payload, key)
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise TokenError(
                "Повреждённый JSON OAuth-клиента", code="CLIENT_SECRETS_INVALID"
            ) from exc
        if not isinstance(data, dict):
            raise TokenError("Неверный формат OAuth-клиента", code="CLIENT_SECRETS_INVALID")
        return data
