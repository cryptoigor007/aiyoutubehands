"""Изоляция тестов от реального окружения оператора.

На машине разработки лежат **боевые** секреты в ``~/.config/aiyoutubehands/``
(``token.age``, ``client_secrets.age``) и живое состояние в
``~/.local/state/aiyoutubehands/`` (``quota.db``, ``calendar.db``).

До появления этого файла прогон тестов создавал файлы в реальном состоянии:
``aiyoutubehands.shorts_maker.processor._run_log_path()`` вызывает
``get_state_dir()`` напрямую и писал ``ayh_run_*.log`` в домашний каталог
оператора.

Здесь ``HOME`` перенаправляется в песочницу **до** импорта ``aiyoutubehands``,
поэтому ``get_config_dir()``, ``get_state_dir()`` и любое ``~``-разворачивание
путей остаются внутри неё.

``XDG_CONFIG_HOME``/``XDG_STATE_HOME`` намеренно **снимаются**, а не
перенаправляются: тесты, проверяющие ``get_config_dir()``/``get_state_dir()``,
выставляют только ``HOME`` и ожидают, что он и определит путь. Если бы conftest
задавал ``XDG_*``, он бы перекрыл их и сломал эти тесты. Тесты, которым нужны
именно XDG-переменные, выставляют их сами через ``monkeypatch``.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

_SANDBOX = Path(tempfile.mkdtemp(prefix="ayh-tests-"))

# HOME определяет и config, и state (get_config_dir/get_state_dir смотрят на
# $XDG_*, а при их отсутствии — на Path.home()).
os.environ["HOME"] = str(_SANDBOX)

# Убираем унаследованные значения, чтобы они не перекрыли HOME в тестах,
# которые переопределяют только HOME.
for _var in ("XDG_CONFIG_HOME", "XDG_STATE_HOME"):
    os.environ.pop(_var, None)

# Эти каталоги config.py не использует, но сторонние библиотеки — могут.
for _var in ("XDG_DATA_HOME", "XDG_CACHE_HOME"):
    _dir = _SANDBOX / _var.lower()
    _dir.mkdir(parents=True, exist_ok=True)
    os.environ[_var] = str(_dir)


@pytest.fixture(scope="session", autouse=True)
def _ayh_sandbox() -> Iterator[Path]:
    """Песочница живёт весь прогон и удаляется после него."""
    yield _SANDBOX
    shutil.rmtree(_SANDBOX, ignore_errors=True)
