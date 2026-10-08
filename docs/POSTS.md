# Записи (Community Posts)

Публикация «Записей» на канал через веб-автоматизацию Safari (macOS).

> **Важно:** официальный YouTube Data API v3 **не поддерживает** создание
> community posts. Эндпоинта нет. Реализация — только UI-автоматизация.

## Требования (macOS)

1. Safari с включённым **Develop → Allow JavaScript from Apple Events**.
2. Для картинки (fallback через нативный пикер): разрешение **Accessibility**
   для Terminal / вашего терминала / Python
   (Системные настройки → Конфиденциальность → Универсальный доступ).
3. `channel.expected_channel_id` в `~/.config/aiyoutubehands/config.yaml`
   (или `config/local.yaml`).

## Требования к картинке (вкладка «Сообщество»)

Обязательно соблюдать при подготовке файла — иначе превью в ленте обрежется
или публикация упадёт.

| Параметр | Значение |
|----------|----------|
| Соотношение сторон | **1:1 (квадрат)** — рекомендуется. В общей ленте кадрируется под квадрат; 16:9 / 9:16 обрежутся по краям. |
| Разрешение | Оптимально **1080×1080 … 1200×1200** px |
| Форматы | JPG, PNG, GIF (в т.ч. анимированный), WEBP |
| Макс. размер файла | **16 МБ** |
| Кол-во в одной записи | До **10** (карусель). Текущая CLI принимает **одно** изображение. |
| Опросы с картинками | 1:1, до 4 вариантов, подпись ≤36 символов — **пока не в CLI** |

CLI при `--image` печатает эти требования в dry-run. Валидация жёстко режет
формат и размер >16 МБ; соотношение сторон — рекомендация (без Pillow не
измеряем пиксели).

## CLI


```bash
# План (ничего не публикует) — по умолчанию
ayh post create --text-file ./post.txt

# С картинкой
ayh post create --text-file ./post.txt --image ./cover.jpg

# JSON-план
ayh post create --text-file ./post.txt --json

# Реальная публикация (только на macOS, после подтверждения)
ayh post create --text-file ./post.txt --image ./cover.jpg --no-dry-run --yes
```

Подтверждение следует правилам репозитория
(`docs/AGENT_PROMPT_PROCESS.md`): фраза вида

```
подтверждаю план от ДД.ММ.ГГГГ #<plan_hash>
```

## Поведение

| Флаг | Действие |
|------|----------|
| `--dry-run` (default) | Показать URL, превью текста, шаги, hash. Safari не трогает. |
| `--no-dry-run --yes` | Открыть диалог, вставить текст, (опц.) картинку, нажать «Опубликовать». |
| Картинка не прикрепилась | **Стоп.** Пост без картинки не публикуется. |

## Архитектура

```
src/aiyoutubehands/posts/
  __init__.py
  models.py    # PostPayload, validate_text_file / validate_image_path
  js.py        # ASCII-safe JS (кириллица → \uXXXX)
  safari.py    # osascript / System Events (только Darwin)
  errors.py    # SafariNotAvailable, ElementTimeout, PublishRejected, …
commands/post_cmd.py
```

Ядро и unit-тесты кроссплатформенные. Реальный прогон — только на Mac.

## Ограничения

- Только «создать сейчас». Отложенной публикации у Записей нет.
- Успех = пост виден на `/posts`. Ответ на клик проверкой не является.
- Серверная ошибка «Не удалось опубликовать запись» детектится и считается провалом.
- Синтетическая подстановка `File` через DataTransfer рисует превью, но
  сервер часто отклоняет пост — поэтому основной путь для картинки:
  нативный file dialog (System Events) или будущий HAR-replay.

## Ручной прогон (чеклист)

1. `ayh post create --text-file t.txt --dry-run` — план корректен.
2. Safari: Develop → Allow JavaScript from Apple Events.
3. `ayh post create --text-file t.txt --no-dry-run --yes`
4. Открыть `https://www.youtube.com/channel/<ID>/posts` — запись на месте.
5. С `--image`: либо пост с картинкой, либо явная ошибка (не молча без неё).

## Тесты

```bash
PYTHONPATH=src pytest tests/test_posts_js.py tests/test_posts_models.py tests/test_posts_cli.py -v
```
