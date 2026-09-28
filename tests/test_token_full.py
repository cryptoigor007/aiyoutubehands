"""Полное покрытие ``aiyoutubehands.token``.

Здесь собраны ветки, не затронутые ``test_token.py``: ошибки ключа/salt/blob,
legacy-формат, ``TokenStore`` (raw/passphrase), audit/health/rotate и
``EncryptedJsonStore``.

ВАЖНО: scrypt N=2**17 стоит ~1.5 c на вызов, поэтому дорогие вызовы
(``derive_key_from_passphrase(n=2**17)``, passphrase-save) сведены к минимуму,
а legacy-ветки проверяются дешёвым N=2**14.
"""

from __future__ import annotations

import json
import stat as stat_mod
from typing import TYPE_CHECKING

import pytest

from aiyoutubehands.token import (
    BLOB_MAGIC,
    BLOB_MODE_PASSPHRASE,
    BLOB_MODE_PASSPHRASE_V2,
    BLOB_MODE_RAW,
    SALT_LEN,
    SCRYPT_N,
    SCRYPT_N_LEGACY,
    EncryptedJsonStore,
    TokenData,
    TokenError,
    TokenStore,
    _ensure_private_dir,
    _scrypt_n_for_mode,
    _write_private,
    decrypt_bytes,
    derive_key_from_passphrase,
    encrypt_bytes,
    pack_blob,
    unpack_blob,
)

if TYPE_CHECKING:
    from pathlib import Path

KEY = b"k" * 32


def _legacy_passphrase_blob(payload: bytes, passphrase: str = "pw") -> bytes:
    """Собрать blob старого формата (mode 1, scrypt N=2**14)."""
    key, salt = derive_key_from_passphrase(passphrase, n=SCRYPT_N_LEGACY)
    return pack_blob(encrypt_bytes(payload, key), mode=BLOB_MODE_PASSPHRASE, salt=salt)


# --- encrypt_bytes / decrypt_bytes -----------------------------------------


def test_encrypt_bytes_rejects_wrong_key_length() -> None:
    with pytest.raises(TokenError) as ei:
        encrypt_bytes(b"data", b"short")
    assert ei.value.code == "TOKEN_BAD_KEY"


def test_decrypt_bytes_rejects_wrong_key_length() -> None:
    with pytest.raises(TokenError) as ei:
        decrypt_bytes(b"x" * 32, b"short")
    assert ei.value.code == "TOKEN_BAD_KEY"


def test_decrypt_bytes_rejects_short_blob() -> None:
    with pytest.raises(TokenError) as ei:
        decrypt_bytes(b"short", KEY)
    assert ei.value.code == "TOKEN_CORRUPT"


def test_decrypt_bytes_wrong_key_is_decrypt_failed() -> None:
    ct = encrypt_bytes(b"data", KEY)
    with pytest.raises(TokenError) as ei:
        decrypt_bytes(ct, b"z" * 32)
    assert ei.value.code == "TOKEN_DECRYPT_FAILED"


# --- TokenData.is_expired ---------------------------------------------------


def test_token_data_is_expired_without_timestamp() -> None:
    assert TokenData(access_token="a").is_expired() is True


def test_token_data_is_expired_false_for_future_timestamp() -> None:
    assert TokenData(access_token="a", expires_at=99_9999_9999).is_expired() is False


# --- derive_key_from_passphrase --------------------------------------------


def test_derive_key_rejects_bad_salt_length() -> None:
    with pytest.raises(TokenError) as ei:
        derive_key_from_passphrase("pw", b"short")
    assert ei.value.code == "TOKEN_BAD_SALT"


def test_derive_key_explicit_legacy_n_is_deterministic() -> None:
    salt = b"s" * SALT_LEN
    key1, salt1 = derive_key_from_passphrase("pw", salt, n=SCRYPT_N_LEGACY)
    key2, _salt2 = derive_key_from_passphrase("pw", salt, n=SCRYPT_N_LEGACY)
    assert len(key1) == 32
    assert salt1 == salt
    assert key1 == key2


def test_derive_key_explicit_strong_n_generates_salt() -> None:
    key, salt = derive_key_from_passphrase("pw", n=2**17)
    assert len(key) == 32
    assert len(salt) == SALT_LEN


def test_scrypt_n_for_mode_maps_modes() -> None:
    assert _scrypt_n_for_mode(BLOB_MODE_PASSPHRASE_V2) == SCRYPT_N
    assert _scrypt_n_for_mode(BLOB_MODE_PASSPHRASE) == SCRYPT_N_LEGACY
    assert _scrypt_n_for_mode(BLOB_MODE_RAW) == SCRYPT_N_LEGACY


# --- pack_blob / unpack_blob ------------------------------------------------


def test_pack_blob_raw_layout() -> None:
    blob = pack_blob(b"payload", mode=BLOB_MODE_RAW)
    assert blob == BLOB_MAGIC + bytes([BLOB_MODE_RAW]) + b"payload"


def test_pack_blob_passphrase_requires_valid_salt() -> None:
    with pytest.raises(TokenError) as ei:
        pack_blob(b"payload", mode=BLOB_MODE_PASSPHRASE, salt=None)
    assert ei.value.code == "TOKEN_BAD_SALT"

    with pytest.raises(TokenError) as ei2:
        pack_blob(b"payload", mode=BLOB_MODE_PASSPHRASE_V2, salt=b"short")
    assert ei2.value.code == "TOKEN_BAD_SALT"


def test_pack_blob_passphrase_layout() -> None:
    salt = b"s" * SALT_LEN
    blob = pack_blob(b"payload", mode=BLOB_MODE_PASSPHRASE_V2, salt=salt)
    assert blob == BLOB_MAGIC + bytes([BLOB_MODE_PASSPHRASE_V2]) + salt + b"payload"


def test_pack_blob_rejects_unknown_mode() -> None:
    with pytest.raises(TokenError) as ei:
        pack_blob(b"payload", mode=99)
    assert ei.value.code == "TOKEN_BAD_MODE"


def test_unpack_blob_raw_roundtrip() -> None:
    mode, salt, payload = unpack_blob(pack_blob(b"payload", mode=BLOB_MODE_RAW))
    assert mode == BLOB_MODE_RAW
    assert salt is None
    assert payload == b"payload"


def test_unpack_blob_passphrase_roundtrip() -> None:
    salt = b"s" * SALT_LEN
    body = b"payload" * 10  # >= 13 байт, иначе unpack_blob сочтёт blob обрезанным
    mode, got_salt, payload = unpack_blob(pack_blob(body, mode=BLOB_MODE_PASSPHRASE_V2, salt=salt))
    assert mode == BLOB_MODE_PASSPHRASE_V2
    assert got_salt == salt
    assert payload == body


def test_unpack_blob_rejects_unknown_mode() -> None:
    blob = BLOB_MAGIC + bytes([99]) + b"x" * 30
    with pytest.raises(TokenError) as ei:
        unpack_blob(blob)
    assert ei.value.code == "TOKEN_BAD_MODE"


def test_unpack_blob_rejects_short_passphrase_payload() -> None:
    blob = BLOB_MAGIC + bytes([BLOB_MODE_PASSPHRASE]) + b"x" * 5
    with pytest.raises(TokenError) as ei:
        unpack_blob(blob)
    assert ei.value.code == "TOKEN_CORRUPT"


def test_unpack_blob_legacy_without_magic_is_raw() -> None:
    mode, salt, payload = unpack_blob(b"legacy-payload")
    assert (mode, salt, payload) == (BLOB_MODE_RAW, None, b"legacy-payload")


def test_unpack_blob_magic_too_short_is_treated_as_legacy() -> None:
    mode, salt, payload = unpack_blob(BLOB_MAGIC)
    assert (mode, salt, payload) == (BLOB_MODE_RAW, None, BLOB_MAGIC)


# --- TokenStore construction -------------------------------------------------


def test_token_store_requires_key_or_passphrase() -> None:
    with pytest.raises(TokenError) as ei:
        TokenStore("/tmp/nowhere")
    assert ei.value.code == "TOKEN_BAD_KEY"


def test_token_store_rejects_bad_key_length() -> None:
    with pytest.raises(TokenError) as ei:
        TokenStore("/tmp/nowhere", key=b"short")
    assert ei.value.code == "TOKEN_BAD_KEY"


def test_resolve_key_without_key_raises() -> None:
    store = TokenStore("/tmp/nowhere", key=KEY)
    store._key = None  # deliberate: simulate corrupted internal state
    with pytest.raises(TokenError) as ei:
        store._resolve_key()
    assert ei.value.code == "TOKEN_NO_KEY"


# --- TokenStore raw mode ----------------------------------------------------


def test_token_store_raw_save_load_and_permissions(tmp_path: Path) -> None:
    path = tmp_path / "secrets" / "token.age"
    audit = tmp_path / "secrets" / "token.audit.jsonl"
    store = TokenStore(path, key=KEY, audit_path=audit)
    store.save(TokenData(access_token="at", refresh_token="rt", expires_at=99_9999_9999))

    assert path.is_file()
    assert stat_mod.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat_mod.S_IMODE(path.stat().st_mode) == 0o600
    assert stat_mod.S_IMODE(audit.stat().st_mode) == 0o600
    assert path.read_bytes().startswith(BLOB_MAGIC)

    loaded = store.load()
    assert loaded.access_token == "at"
    assert loaded.refresh_token == "rt"

    entries = [json.loads(line) for line in audit.read_text().splitlines()]
    assert entries[-1]["action"] == "save"


def test_audit_appends_explicit_entry(tmp_path: Path) -> None:
    audit = tmp_path / "audit.jsonl"
    store = TokenStore(tmp_path / "t.age", key=KEY, audit_path=audit)
    store.audit("rotate", detail="manual")
    lines = audit.read_text().strip().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["action"] == "rotate"
    assert payload["detail"] == "manual"


def test_token_store_load_missing_file(tmp_path: Path) -> None:
    store = TokenStore(tmp_path / "missing.age", key=KEY)
    with pytest.raises(TokenError) as ei:
        store.load()
    assert ei.value.code == "TOKEN_NOT_FOUND"


def test_token_store_health_missing_file(tmp_path: Path) -> None:
    store = TokenStore(tmp_path / "missing.age", key=KEY)
    health = store.health()
    assert health["ok"] is False
    assert health["error"] == "TOKEN_NOT_FOUND"


def test_token_store_health_broken_file(tmp_path: Path) -> None:
    path = tmp_path / "broken.age"
    path.write_bytes(b"garbage")
    health = TokenStore(path, key=KEY).health()
    assert health["ok"] is False
    assert health["error"] in {"TOKEN_CORRUPT", "TOKEN_DECRYPT_FAILED"}


def test_token_store_health_ok_reports_fields(tmp_path: Path) -> None:
    path = tmp_path / "token.age"
    store = TokenStore(path, key=KEY)
    store.save(TokenData(access_token="a", refresh_token="r", expires_at=1))
    health = store.health()
    assert health["ok"] is True
    assert health["has_access"] is True
    assert health["has_refresh"] is True
    assert health["expired"] is True


def test_token_store_load_raw_json_corrupt(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.age"
    path.write_bytes(pack_blob(encrypt_bytes(b"not-json", KEY), mode=BLOB_MODE_RAW))
    with pytest.raises(TokenError) as ei:
        TokenStore(path, key=KEY).load()
    assert ei.value.code == "TOKEN_CORRUPT"


def test_token_store_with_passphrase_cannot_read_raw_blob(tmp_path: Path) -> None:
    path = tmp_path / "raw.age"
    path.write_bytes(pack_blob(encrypt_bytes(b"{}", KEY), mode=BLOB_MODE_RAW))
    with pytest.raises(TokenError) as ei:
        TokenStore(path, passphrase="pw").load()
    assert ei.value.code == "TOKEN_BAD_KEY"


def test_token_store_with_key_cannot_read_passphrase_blob(tmp_path: Path) -> None:
    path = tmp_path / "pass.age"
    path.write_bytes(_legacy_passphrase_blob(b"{}"))
    with pytest.raises(TokenError) as ei:
        TokenStore(path, key=KEY).load()
    assert ei.value.code == "TOKEN_BAD_KEY"


def test_token_store_rotate_access_saves_and_audits(tmp_path: Path) -> None:
    path = tmp_path / "token.age"
    audit = tmp_path / "audit.jsonl"
    store = TokenStore(path, key=KEY, audit_path=audit)
    store.save(TokenData(access_token="old", refresh_token="r", expires_at=1))

    rotated = store.rotate_access("new-access", 99_9999_9999)
    assert rotated.access_token == "new-access"
    assert store.load().access_token == "new-access"

    actions = [json.loads(line)["action"] for line in audit.read_text().splitlines()]
    assert "rotate" in actions


# --- TokenStore passphrase mode ---------------------------------------------


def test_token_store_passphrase_save_uses_v2(tmp_path: Path) -> None:
    """Единственный дорогой вызов N=2**17: passphrase-save пишет mode 2."""
    path = tmp_path / "token.ayh"
    store = TokenStore(path, passphrase="secret")
    store.save(TokenData(access_token="at", refresh_token="rt", expires_at=99_9999_9999))

    mode, salt, _payload = unpack_blob(path.read_bytes())
    assert mode == BLOB_MODE_PASSPHRASE_V2
    assert salt is not None and len(salt) == SALT_LEN


def test_legacy_passphrase_blob_loads_via_store(tmp_path: Path) -> None:
    """Старый mode 1 читается дешёвым scrypt N=2**14 и даёт верные данные."""
    path = tmp_path / "legacy.ayh"
    payload = json.dumps(
        {"access_token": "old-at", "refresh_token": "r", "expires_at": 99_9999_9999}
    ).encode()
    path.write_bytes(_legacy_passphrase_blob(payload))

    loaded = TokenStore(path, passphrase="pw").load()
    assert loaded.access_token == "old-at"
    assert loaded.refresh_token == "r"


# --- low-level file helpers -------------------------------------------------


def test_write_private_and_ensure_private_dir_permissions(tmp_path: Path) -> None:
    d = tmp_path / "secrets"
    _ensure_private_dir(d)
    assert stat_mod.S_IMODE(d.stat().st_mode) == 0o700

    p = d / "blob.bin"
    _write_private(p, b"secret")
    assert p.read_bytes() == b"secret"
    assert stat_mod.S_IMODE(p.stat().st_mode) == 0o600


# --- EncryptedJsonStore -----------------------------------------------------


def test_encrypted_json_store_requires_passphrase(tmp_path: Path) -> None:
    with pytest.raises(TokenError) as ei:
        EncryptedJsonStore(tmp_path / "s.age", passphrase="")
    assert ei.value.code == "TOKEN_BAD_KEY"


def test_encrypted_json_store_missing_file(tmp_path: Path) -> None:
    with pytest.raises(TokenError) as ei:
        EncryptedJsonStore(tmp_path / "missing.age", passphrase="pw").load()
    assert ei.value.code == "CLIENT_SECRETS_MISSING"


def test_encrypted_json_store_rejects_unencrypted_blob(tmp_path: Path) -> None:
    path = tmp_path / "raw.age"
    path.write_bytes(pack_blob(b"{}", mode=BLOB_MODE_RAW))
    with pytest.raises(TokenError) as ei:
        EncryptedJsonStore(path, passphrase="pw").load()
    assert ei.value.code == "CLIENT_SECRETS_UNENCRYPTED"


def test_encrypted_json_store_rejects_corrupt_json(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.age"
    path.write_bytes(_legacy_passphrase_blob(b"not-json"))
    with pytest.raises(TokenError) as ei:
        EncryptedJsonStore(path, passphrase="pw").load()
    assert ei.value.code == "CLIENT_SECRETS_INVALID"


def test_encrypted_json_store_rejects_non_dict_payload(tmp_path: Path) -> None:
    path = tmp_path / "list.age"
    path.write_bytes(_legacy_passphrase_blob(json.dumps([1, 2, 3]).encode()))
    with pytest.raises(TokenError) as ei:
        EncryptedJsonStore(path, passphrase="pw").load()
    assert ei.value.code == "CLIENT_SECRETS_INVALID"


def test_encrypted_json_store_save_roundtrip(tmp_path: Path) -> None:
    """Дорогой N=2**17: проверяем запись, права и обратное чтение."""
    path = tmp_path / "client_secrets.age"
    store = EncryptedJsonStore(path, passphrase="secret-pass")
    store.save({"client_id": "cid", "client_secret": "csecret"})

    assert b"csecret" not in path.read_bytes()
    assert stat_mod.S_IMODE(path.stat().st_mode) == 0o600
    loaded = EncryptedJsonStore(path, passphrase="secret-pass").load()
    assert loaded["client_id"] == "cid"
