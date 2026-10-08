# Записи (Community Posts)

Публикация «Записей» на канал через Safari (macOS). Официальный YouTube Data API v3
**не поддерживает** создание community posts — эндпоинта нет. Команда воспроизводит
**веб-флоу из контекста страницы** (Safari + Apple Events) — так же, как это делает сам сайт.

## Два пути публикации

| Путь | Что делает | Требования |
|------|------------|------------|
| `api` (по умолчанию) | fetch-реплей из вкладки youtube.com: upload init → upload finalize (`encryptedBlobId`) → `backstage/create_post` (текст + картинка + кадр) | macOS + Safari + **Allow JavaScript from Apple Events** + залогиненная вкладка `www.youtube.com` |
| `ui` (fallback) | DOM-автоматизация диалога «Создать запись» — **только текст** | то же |

Поток `api` снят с реального прогона **08.10.2026** (заголовки, тела, `previewCoordinates` —
см. `~/.opencode/plan/posts_js_20261007/POSTS_NETLOG_FINDINGS.md`).

## Требования (macOS)

1. Safari с включённым **Develop → Allow JavaScript from Apple Events**.
2. Залогиненная вкладка **www.youtube.com** (команда сама найдёт или откроет её).
3. `channel.expected_channel_id` в `~/.config/aiyoutubehands/config.yaml` (или `config/local.yaml`).
4. **Accessibility / System Events не нужны** — они требовались только старому пути
   через нативный пикер, который больше не используется.

## Требования к картинке (вкладка «Сообщество»)

| Параметр | Значение |
|----------|----------|
| Соотношение сторон | **1:1 (квадрат)** — рекомендуется. В ленте кадрируется под квадрат; для не-квадратных команда сама выставляет кадр (`--crop`). |
| Разрешение | Оптимально **1080×1080 … 1200×1200** px |
| Форматы | JPG, PNG, GIF (в т.ч. анимированный), WEBP |
| Макс. размер файла | **16 МБ** |
| Кол-во в одной записи | До **10** (карусель). Текущая CLI принимает **одно** изображение. |
| Опросы с картинками | 1:1, до 4 вариантов, подпись ≤36 символов — **пока не в CLI** |

`--crop` (для не-квадратных): `center` (по умолчанию) · `left` · `right` · `top` · `bottom`.
Размеры картинки читаются без Pillow (заголовки JPEG/PNG/GIF/WEBP); если не распознались —
кадр выставляется полный и команда печатает предупреждение.

## CLI

```bash
# План (ничего не публикует) — по умолчанию
ayh post create --text-file ./post.txt

# С картинкой и кадром
ayh post create --text-file ./post.txt --image ./cover.jpg --crop right

# JSON-план
ayh post create --text-file ./post.txt --json

# Реальная публикация (только macOS, после подтверждения)
ayh post create --text-file ./post.txt --image ./cover.jpg --crop right \
  --no-dry-run --yes \
  --confirm "подтверждаю план от ДД.ММ.ГГГГ #<plan_hash>"
```

Подтверждение — по правилам репозитория (`docs/AGENT_PROMPT_PROCESS.md`):
фраза с **сегодняшней датой** и **hash из dry-run**; иначе публикации не будет.

## Поведение

| Флаг | Действие |
|------|----------|
| `--dry-run` (default) | Показать URL, путь, превью текста, размер/кадр картинки, шаги, hash и фразу. Safari не трогает. |
| `--no-dry-run --yes --confirm "…"` | Выполнить публикацию выбранным путём. |
| `--via ui` | Fallback: DOM-клики (только текст; картинка — ошибка с подсказкой). |
| Картинка не загрузилась | **Стоп.** Пост без картинки не публикуется. |
| Проверка успеха | После `create_post` команда ищет пост на `/posts` (best-effort). `OK` без `verified` — проверьте глазами. |

## Архитектура

```
src/aiyoutubehands/posts/
  __init__.py
  models.py    # PostPayload, валидация текста/картинки, crop
  webapi.py    # protobuf-параметры, координаты кадра, размеры картинок (чистый Python)
  js.py        # ASCII-safe JS: UI-клики + fetch-реплей (upload / create_post)
  safari.py    # драйвер Safari: файловый do JavaScript, вкладки, опрос async-результатов
  errors.py    # SafariNotAvailable, ElementTimeout, PublishRejected, ImageAttachFailed, …
commands/post_cmd.py
```

Ядро и unit-тесты кроссплатформенные. Реальный прогон — только на Mac.

## Ограничения и заметки

- Только «создать сейчас» — отложенной публикации у Записей нет.
- Веб-флоу неофициальный: если YouTube поменяет схему, обновляем по свежей лог-съёмке
  (`net_hooks3.js` в `~/.opencode/plan/posts_js_20261007/`).
- Если сервер отвечает `401/403` на `create_post`, команда сама вычисляет `SAPISIDHASH`
  из доступной JS-куки (`__Secure-3PAPISID`) и повторяет запрос один раз.
- Большие картинки передаются чанками (b64) в страницу; лимит 16 МБ как в Studio.
- Синтетическая подстановка `File` через DataTransfer в UI-диалог **не используется** —
  сервер отклонял такие публикации; путь `api` отправляет байты штатным resumable-upload.

## Тесты

```bash
PYTHONPATH=src pytest tests/test_posts_webapi.py tests/test_posts_js.py \
  tests/test_posts_models.py tests/test_posts_cli.py -v
```
