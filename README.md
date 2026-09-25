# AI YouTube Hands

AI-first CLI для полного управления YouTube-каналом.

**Бинарник:** `ayh`  
**Пакет:** `aiyoutubehands`  
**Версия:** 0.1.0

## Быстрый старт

```bash
cd aiyoutubehands
PYTHONPATH=src python3 -m aiyoutubehands.main doctor
PYTHONPATH=src python3 -m aiyoutubehands.main ai title "мой топик"
PYTHONPATH=src python3 -m aiyoutubehands.main calendar grid --year 2026 --month 10
PYTHONPATH=src python3 -m aiyoutubehands.main quota status
```

## Команды

| Группа | Команды |
|--------|---------|
| doctor | диагностика |
| version | версия |
| auth | status, login (--stub) |
| channel | info (dry-run) |
| video | info (dry-run) |
| calendar | list, grid, add |
| quota | status |
| ai | title, description, tags, script, thumbnail |
| upload | prepare (dry-run only) |

## Безопасность

- Нет реальных мутаций YouTube без явного разрешения
- Токены шифруются (AES-GCM)
- Квоты учитываются
- `expected_channel_id` проверяется

## Разработка

```bash
PYTHONPATH=src python3 -m pytest tests/ -q
```

См. `docs/ARCHITECTURE.md` и Master Agent Charter.
