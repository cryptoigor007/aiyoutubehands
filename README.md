# AI YouTube Hands

AI-first CLI для управления YouTube-каналом.

**Бинарник:** `ayh` · **Пакет:** `aiyoutubehands` · **Версия:** 0.1.0

## Быстрый старт

```bash
cd aiyoutubehands
PYTHONPATH=src python3 -m aiyoutubehands.main doctor
PYTHONPATH=src python3 -m aiyoutubehands.main auth login --stub --passphrase 'secret' --yes
PYTHONPATH=src python3 -m aiyoutubehands.main auth status --passphrase 'secret'
PYTHONPATH=src python3 -m aiyoutubehands.main ai title "тема"
```

## Важно

- Реальных мутаций YouTube нет без отдельного разрешения.
- Upload только `prepare` (dry-run).
- OAuth login в режиме `--stub` (реальный Device Flow — следующий этап).

## Тесты

```bash
PYTHONPATH=src python3 -m pytest tests/ -q
```
