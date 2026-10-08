# Ручной прогон «Записи» на macOS

Чеклист для владельца канала / агента на Маке. Актуально для ветки `feat/community-posts`.

## Подготовка (один раз)

1. Safari → меню **Develop** → включить **Allow JavaScript from Apple Events**.
   Если меню Develop нет: Safari → Settings → Advanced → Show Develop menu.
2. Убедиться, что в Safari есть **залогиненная вкладка youtube.com** (команда сама её найдёт
   или откроет `/channel/<ID>/posts`).
3. В `~/.config/aiyoutubehands/config.yaml` должен быть:
   ```yaml
   channel:
     expected_channel_id: "UC…"
   ```

> Accessibility / System Events для пути по умолчанию (`api`) **не нужны**.

## Тест 1 — dry-run (обязательно)

```bash
cd ~/aiyoutubehands-v0.2
git checkout feat/community-posts
PYTHONPATH=src python -m aiyoutubehands.main post create --text-file /tmp/post.txt
```

Ожидание: план (путь `api`, URL, превью текста, hash, фраза подтверждения). Safari не трогается.

## Тест 2 — текст без картинки

```bash
echo "Тестовая запись $(date +%H:%M)" > /tmp/post.txt
PYTHONPATH=src python -m aiyoutubehands.main post create \
  --text-file /tmp/post.txt --no-dry-run --yes \
  --confirm "подтверждаю план от ДД.ММ.ГГГГ #<hash из dry-run>"
```

Ожидание: «Сервер принял публикацию», проверка ленты `/posts`.

## Тест 3 — с картинкой (например, 16:9 с кадром «правая часть»)

```bash
PYTHONPATH=src python -m aiyoutubehands.main post create \
  --text-file /tmp/post.txt --image /path/to/image.jpg --crop right \
  --no-dry-run --yes \
  --confirm "подтверждаю план от ДД.ММ.ГГГГ #<hash из dry-run>"
```

Ожидание: `upload init → передача байтов → finalize (encryptedBlobId) → create_post`;
либо пост **с** картинкой, либо явная ошибка.  
**Не** должно быть молчаливой публикации без картинки.

## Верификация успеха

Открыть вручную: `https://www.youtube.com/channel/<CHANNEL_ID>/posts`

Пост должен быть виден. Строка `verified: true` от команды — хороший признак,
но глазами надёжнее.

## Если упало

| Симптом | Действие |
|---------|----------|
| osascript / Safari unavailable | Только macOS; проверьте Develop → Allow JS from Apple Events |
| «внутренняя ошибка: JS не ASCII-safe» | Баг в билдере — сообщить разработчику |
| «Пустой ответ Safari JS» / таймаут | Вкладка youtube.com не догрузилась — обновите её и повторите |
| `upload init`/`finalize` ошибка | Повторите; если повторяется — снять свежий лог сети (`net_hooks3.js`) |
| Сервер отклонил публикацию (`status=…`) | Смотрите `responseHead`; проверьте текст/картинку вручную в Studio |

## Тесты (кроссплатформенные)

```bash
PYTHONPATH=src pytest tests/test_posts_webapi.py tests/test_posts_js.py \
  tests/test_posts_models.py tests/test_posts_cli.py -v
```
