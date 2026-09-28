"""Полное покрытие ``commands/auth_cmd.py`` без сети и без браузера.

Реальный OAuth-поток и сервер колбэка не запускаются: ``desktop_flow_authorize``
и ``load_client_secrets`` подменяются. ``device_flow_*_stub`` — офлайн-ветка.
Пароль локального хранилища передаётся интерактивно через ``input=``
(флага ``--passphrase`` в CLI нет).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from click.testing import CliRunner, Result

from aiyoutubehands import auth_flow
from aiyoutubehands.commands import auth_cmd
from aiyoutubehands.main import cli
from aiyoutubehands.token import EncryptedJsonStore, TokenData, TokenStore

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

PASSWORD = "test-pass"
TOKEN_REL = ".config/aiyoutubehands/token.age"
SECRETS_REL = ".config/aiyoutubehands/client_secrets.age"


# --------------------------------------------------------------------------
# Хелперы
# --------------------------------------------------------------------------


def _invoke(args: list[str], *, stdin: str | None = None) -> Result:
    return CliRunner().invoke(cli, args, input=stdin)


def _make_token(path: Path, passphrase: str = PASSWORD) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    TokenStore(path=path, passphrase=passphrase).save(
        TokenData(access_token="access", refresh_token="refresh", expires_at=9_999_999_999)
    )


def _client_json(tmp_path: Path, client_id: str = "cid", secret: str = "cs") -> Path:
    src = tmp_path / "client_secret.json"
    src.write_text(
        json.dumps({"installed": {"client_id": client_id, "client_secret": secret}}),
        encoding="utf-8",
    )
    return src


# --------------------------------------------------------------------------
# _token_path / _secrets_path / _local_passphrase
# --------------------------------------------------------------------------


def test_token_path_defaults_to_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    assert auth_cmd._token_path() == tmp_path / TOKEN_REL


def test_token_path_falls_back_on_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    def _boom() -> None:
        raise RuntimeError("no config")

    monkeypatch.setattr(auth_cmd, "load_config_optional", _boom)
    assert auth_cmd._token_path() == tmp_path / TOKEN_REL


def test_secrets_path_defaults_to_config_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    assert auth_cmd._secrets_path() == tmp_path / SECRETS_REL


def test_secrets_path_falls_back_on_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    def _boom() -> None:
        raise RuntimeError("no config")

    monkeypatch.setattr(auth_cmd, "load_config_optional", _boom)
    assert auth_cmd._secrets_path() == tmp_path / SECRETS_REL


def test_local_passphrase_returns_explicit_value() -> None:
    assert auth_cmd._local_passphrase("given") == "given"


def test_local_passphrase_prompts_hidden_with_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def _prompt(text: str, **kwargs: Any) -> str:
        captured["text"] = text
        captured["kwargs"] = kwargs
        return "typed"

    monkeypatch.setattr(auth_cmd.click, "prompt", _prompt)
    assert auth_cmd._local_passphrase(None, confirm=True) == "typed"
    assert captured["kwargs"]["hide_input"] is True
    assert captured["kwargs"]["confirmation_prompt"] is True


# --------------------------------------------------------------------------
# auth status
# --------------------------------------------------------------------------


def test_auth_status_no_token_plain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    result = _invoke(["auth", "status"])
    assert result.exit_code == 0
    assert "токен не настроен" in result.output


def test_auth_status_no_token_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    result = _invoke(["auth", "status", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"ok": False, "message": "Токен не настроен"}


def test_auth_status_ok_plain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _make_token(tmp_path / TOKEN_REL)
    result = _invoke(["auth", "status"], stdin=PASSWORD + "\n")
    assert result.exit_code == 0
    assert "auth: OK" in result.output
    assert "expired: False" in result.output


def test_auth_status_ok_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _make_token(tmp_path / TOKEN_REL)
    result = _invoke(["auth", "status", "--json"], stdin=PASSWORD + "\n")
    assert result.exit_code == 0
    # Перед JSON-выводом идёт интерактивное приглашение пароля — отбрасываем его.
    health = json.loads(result.stdout[result.stdout.find("{") :])
    assert health["ok"] is True
    assert health["has_access"] is True
    assert health["has_refresh"] is True


def test_auth_status_wrong_passphrase_exits_10(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _make_token(tmp_path / TOKEN_REL)
    result = _invoke(["auth", "status"], stdin="wrong-pass\n")
    assert result.exit_code == 10
    assert "auth: ошибка" in result.output
    assert "TOKEN_DECRYPT_FAILED" in result.output


# --------------------------------------------------------------------------
# auth login
# --------------------------------------------------------------------------


def test_auth_login_stub_saves_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    result = _invoke(["auth", "login", "--stub", "--yes"], stdin=PASSWORD + "\n")
    assert result.exit_code == 0
    assert "auth login: OK" in result.output
    assert (tmp_path / TOKEN_REL).is_file()


def test_auth_login_existing_without_yes_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _make_token(tmp_path / TOKEN_REL)
    result = _invoke(["auth", "login"], stdin=PASSWORD + "\n")
    assert result.exit_code == 2
    assert "Токен уже есть" in result.output


def test_auth_login_existing_with_yes_overwrites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _make_token(tmp_path / TOKEN_REL)
    result = _invoke(["auth", "login", "--stub", "--yes"], stdin=PASSWORD + "\n")
    assert result.exit_code == 0
    assert "auth login: OK" in result.output


def test_auth_login_real_path_uses_desktop_flow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    captured: dict[str, Any] = {}

    def _load(path: Path, *, passphrase: str) -> dict[str, Any]:
        captured["load_path"] = path
        captured["passphrase"] = passphrase
        return {"client_id": "cid", "client_secret": "cs"}

    def _authorize(client_id: str, client_secret: str, **kwargs: Any) -> TokenData:
        captured["authorize"] = (client_id, client_secret)
        return TokenData(access_token="A", refresh_token="R", expires_at=9_999_999_999)

    monkeypatch.setattr(auth_flow, "load_client_secrets", _load)
    monkeypatch.setattr(auth_flow, "desktop_flow_authorize", _authorize)

    result = _invoke(["auth", "login"], stdin=PASSWORD + "\n")
    assert result.exit_code == 0
    assert captured["authorize"] == ("cid", "cs")
    assert captured["passphrase"] == PASSWORD
    assert captured["load_path"] == tmp_path / SECRETS_REL
    assert "Токен сохранён" in result.output
    stored = TokenStore(path=tmp_path / TOKEN_REL, passphrase=PASSWORD).load()
    assert stored.access_token == "A"


def test_auth_login_real_path_missing_client_secret_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        auth_flow,
        "load_client_secrets",
        lambda path, *, passphrase: {"client_id": "cid"},
    )
    result = _invoke(["auth", "login"], stdin=PASSWORD + "\n")
    assert result.exit_code == 2
    assert "client_secret" in result.output


# --------------------------------------------------------------------------
# auth import-client-secrets
# --------------------------------------------------------------------------


def test_auth_import_client_secrets_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    src = _client_json(tmp_path, client_id="new-id", secret="new-secret")

    result = _invoke(
        ["auth", "import-client-secrets", "--source", str(src)],
        stdin=f"{PASSWORD}\n{PASSWORD}\n",
    )
    assert result.exit_code == 0
    assert "OAuth-клиент зашифрован" in result.output
    assert "Исходный JSON не удалён" in result.output

    loaded = EncryptedJsonStore(tmp_path / SECRETS_REL, passphrase=PASSWORD).load()
    assert loaded == {"client_id": "new-id", "client_secret": "new-secret"}


def test_auth_import_client_secrets_existing_without_yes_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    secrets_path = tmp_path / SECRETS_REL
    secrets_path.parent.mkdir(parents=True, exist_ok=True)
    secrets_path.write_bytes(b"already-there")
    src = _client_json(tmp_path)

    result = _invoke(["auth", "import-client-secrets", "--source", str(src)])
    assert result.exit_code == 2
    assert "уже есть" in result.output
    assert secrets_path.read_bytes() == b"already-there"


def test_auth_import_client_secrets_yes_overwrites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    secrets_path = tmp_path / SECRETS_REL
    EncryptedJsonStore(secrets_path, passphrase="old").save({"client_id": "old"})
    src = _client_json(tmp_path, client_id="fresh", secret="fresh-secret")

    result = _invoke(
        ["auth", "import-client-secrets", "--source", str(src), "--yes"],
        stdin=f"{PASSWORD}\n{PASSWORD}\n",
    )
    assert result.exit_code == 0
    loaded = EncryptedJsonStore(secrets_path, passphrase=PASSWORD).load()
    assert loaded == {"client_id": "fresh", "client_secret": "fresh-secret"}


def test_auth_import_client_secrets_invalid_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    src = tmp_path / "bad.json"
    src.write_text(json.dumps({"foo": "bar"}), encoding="utf-8")

    result = _invoke(
        ["auth", "import-client-secrets", "--source", str(src)],
        stdin=f"{PASSWORD}\n{PASSWORD}\n",
    )
    assert result.exit_code != 0
    assert isinstance(result.exception, auth_flow.AuthFlowError)
    assert result.exception.code == "CLIENT_SECRETS_INVALID"


# --------------------------------------------------------------------------
# auth logout
# --------------------------------------------------------------------------


def test_auth_logout_nothing_to_remove(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    result = _invoke(["auth", "logout"])
    assert result.exit_code == 0
    assert "нечего удалять" in result.output


def test_auth_logout_requires_yes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _make_token(tmp_path / TOKEN_REL)
    result = _invoke(["auth", "logout"])
    assert result.exit_code == 2
    assert "Передайте --yes" in result.output
    assert (tmp_path / TOKEN_REL).is_file()


def test_auth_logout_yes_removes_token_and_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    token = tmp_path / TOKEN_REL
    _make_token(token)
    audit = token.with_suffix(".audit.jsonl")
    audit.write_text("{}\n", encoding="utf-8")

    result = _invoke(["auth", "logout", "--yes"])
    assert result.exit_code == 0
    assert "auth logout: OK" in result.output
    assert not token.exists()
    assert not audit.exists()


def test_auth_logout_yes_only_audit_exists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    token = tmp_path / TOKEN_REL
    token.parent.mkdir(parents=True, exist_ok=True)
    audit = token.with_suffix(".audit.jsonl")
    audit.write_text("{}\n", encoding="utf-8")

    result = _invoke(["auth", "logout", "--yes"])
    assert result.exit_code == 0
    assert "auth logout: OK" in result.output
    assert not audit.exists()
    assert not token.exists()
