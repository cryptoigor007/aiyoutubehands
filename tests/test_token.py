"""Tests for token management."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aiyoutubehands.token import (
    EncryptedJsonStore,
    TokenError,
    TokenStore,
    TokenData,
    encrypt_bytes,
    decrypt_bytes,
)


def test_encrypt_decrypt_roundtrip() -> None:
    key = b"0" * 32
    plaintext = b'{"access_token":"secret"}'
    ciphertext = encrypt_bytes(plaintext, key)
    assert ciphertext != plaintext
    assert decrypt_bytes(ciphertext, key) == plaintext


def test_encrypt_wrong_key_fails() -> None:
    key = b"0" * 32
    bad = b"1" * 32
    ct = encrypt_bytes(b"data", key)
    with pytest.raises(TokenError):
        decrypt_bytes(ct, bad)


def test_token_store_save_load(tmp_path: Path) -> None:
    path = tmp_path / "token.age"
    key = b"k" * 32
    store = TokenStore(path=path, key=key)
    data = TokenData(
        access_token="at",
        refresh_token="rt",
        expires_at=9999999999,
        token_type="Bearer",
        scopes=["youtube"],
    )
    store.save(data)
    assert path.is_file()
    loaded = store.load()
    assert loaded.access_token == "at"
    assert loaded.refresh_token == "rt"


def test_token_store_missing_raises(tmp_path: Path) -> None:
    store = TokenStore(path=tmp_path / "missing.age", key=b"k" * 32)
    with pytest.raises(TokenError) as ei:
        store.load()
    assert ei.value.code == "TOKEN_NOT_FOUND"


def test_token_health_ok(tmp_path: Path) -> None:
    path = tmp_path / "token.age"
    key = b"k" * 32
    store = TokenStore(path=path, key=key)
    store.save(TokenData(access_token="a", refresh_token="r", expires_at=9999999999))
    h = store.health()
    assert h["ok"] is True
    assert h["has_refresh"] is True


def test_audit_log(tmp_path: Path) -> None:
    path = tmp_path / "token.age"
    key = b"k" * 32
    store = TokenStore(path=path, key=key, audit_path=tmp_path / "audit.jsonl")
    store.save(TokenData(access_token="a", refresh_token="r", expires_at=1))
    store.audit("rotate", detail="test")
    lines = (tmp_path / "audit.jsonl").read_text().strip().splitlines()
    assert len(lines) >= 1
    assert "rotate" in lines[-1]


def test_passphrase_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "token.ayh"
    store = TokenStore(path=path, passphrase="secret-pass")
    data = TokenData(access_token="at", refresh_token="rt", expires_at=9999999999)
    store.save(data)
    loaded = TokenStore(path=path, passphrase="secret-pass").load()
    assert loaded.access_token == "at"
    assert loaded.refresh_token == "rt"


def test_passphrase_wrong_fails(tmp_path: Path) -> None:
    path = tmp_path / "token.ayh"
    TokenStore(path=path, passphrase="good").save(
        TokenData(access_token="a", refresh_token="r", expires_at=1)
    )
    with pytest.raises(TokenError):
        TokenStore(path=path, passphrase="bad").load()


def test_versioned_blob_magic(tmp_path: Path) -> None:
    path = tmp_path / "token.ayh"
    key = b"k" * 32
    TokenStore(path=path, key=key).save(TokenData(access_token="a", refresh_token="r", expires_at=1))
    raw = path.read_bytes()
    assert raw.startswith(b"AYH1")


def test_encrypted_json_store_roundtrip_and_permissions(tmp_path: Path) -> None:
    path = tmp_path / "client_secrets.age"
    EncryptedJsonStore(path, passphrase="secret-pass").save(
        {"client_id": "client-id", "client_secret": "client-secret"}
    )
    assert b"client-secret" not in path.read_bytes()
    assert path.stat().st_mode & 0o777 == 0o600
    loaded = EncryptedJsonStore(path, passphrase="secret-pass").load()
    assert loaded["client_id"] == "client-id"
