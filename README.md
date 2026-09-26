# AI YouTube Hands (`ayh`)

AI-first CLI для YouTube Data API v3.

## Установка (dev)

```bash
cd aiyoutubehands
PYTHONPATH=src python3 -m aiyoutubehands.main doctor
```

## Настройка

1. В Google Cloud включите **YouTube Data API v3** и создайте OAuth client типа **Desktop app**.
2. Скачанный JSON OAuth-клиента импортируйте в зашифрованное хранилище. При запросе введите локальный пароль; не передавайте его в параметре команды.

```bash
ayh auth import-client-secrets --source ~/Downloads/client_secret_*.json
```

После успешного импорта удалите исходный JSON из `Downloads`.

3. `~/.config/aiyoutubehands/config.yaml`:

```yaml
channel:
  expected_channel_id: "UCxxxxxxxx"
auth:
  client_secrets_file: "~/.config/aiyoutubehands/client_secrets.age"
  token_file: "~/.config/aiyoutubehands/token.age"
```

4. Логин: команда откроет системный браузер, где нужно выбрать Google-аккаунт с каналом и подтвердить доступ.

```bash
PYTHONPATH=src python3 -m aiyoutubehands.main auth login --yes
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

Мутации по умолчанию **dry-run**. Реально: `--no-dry-run --yes`; пароль хранилища вводится в скрытом приглашении.

## Тесты

```bash
PYTHONPATH=src python3 -m pytest tests/ -q
```
