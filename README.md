# AI YouTube Hands (`ayh`)

AI-first CLI для YouTube Data API v3.

## Установка (dev)

```bash
cd aiyoutubehands
PYTHONPATH=src python3 -m aiyoutubehands.main doctor
```

## Настройка

1. Google Cloud: включите **YouTube Data API v3**, создайте OAuth client (TV/Limited Input или Desktop).
2. Сохраните JSON как `~/.config/aiyoutubehands/client_secrets.json`
3. `~/.config/aiyoutubehands/config.yaml`:

```yaml
channel:
  expected_channel_id: "UCxxxxxxxx"
auth:
  client_secrets_file: "~/.config/aiyoutubehands/client_secrets.json"
  token_file: "~/.config/aiyoutubehands/token.age"
```

4. Логин:

```bash
PYTHONPATH=src python3 -m aiyoutubehands.main auth login --passphrase 'SECRET' --yes
# или офлайн: --stub
```

## Команды

| Группа | Действия |
|--------|----------|
| auth | login / logout / status |
| channel | info |
| video | info, publish, schedule, delete, thumbnail |
| upload | prepare, run (resumable) |
| playlist | list, create, add, delete |
| comments | list, reply, moderate |
| captions | list, upload |
| calendar | list, grid, add |
| quota | status |
| ai | title, description, tags, script, thumbnail, chapters, translate, calendar |
| doctor | диагностика |

Мутации по умолчанию **dry-run**. Реально: `--no-dry-run --yes --passphrase …`

## Тесты

```bash
PYTHONPATH=src python3 -m pytest tests/ -q
```
