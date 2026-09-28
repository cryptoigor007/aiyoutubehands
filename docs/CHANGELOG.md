# Changelog

## 0.2.1

Аудит и правки безопасности (см. `AUDIT.md`).

- **matcher**: убран фолбэк «единственное недавнее видео» — папка без совпадения
  по заголовку больше не захватывает видео и не перезаписывает его целиком
- **processor**: маркер `#ayh_processed` резервирует место до обрезки описания;
  отказ `publishAt` больше не выглядит как полный успех (второй `videos.update`
  учтён в квоте, в отчёте — предупреждение)
- **models**: `to_api()` не отправляет незаданные поля — смена заголовка не
  затирает описание, `videos.update` не сбрасывает COPPA-флаг
- **auth**: убраны 10 голых `assert`; единый страж `NOT_AUTHENTICATED` до сети;
  `--passphrase` убран со всех команд (только интерактивный ввод)
- **youtube**: гарда канала на всех путях записи, fail-closed без
  `expected_channel_id`; `list_playlists` читает `nextPageToken`
- **process**: подтверждение привязано к хэшу плана
  (`подтверждаю план от ДД.ММ.ГГГГ #<хэш>`); `apply` печатает план и умеет
  `--plan <файл>` для сверки
- **upload**: управляемый `notifySubscribers`
  (`--notify-subscribers/--no-notify-subscribers`)
- **security**: scrypt N=2**17 с обратной совместимостью для старых блобов;
  каталог секретов 0700, файл создаётся сразу с 0600; `trust_env=False`
- **tests**: изоляция от реального `$HOME` (`tests/conftest.py`)

## 0.2.0

- **process** — безопасный пост-процессинг уже загруженных видео из папки Shorts Maker
  - `ayh process analyze` / `apply` / `run`
  - сканирование подпапок, маркеры ПЕРЕДЕЛАТЬ / НУЖНО РАЗОБРАТЬСЯ
  - сопоставление: title → video id → duration±1s (ffprobe) + date
  - план-таблица + квота; подтверждение фразой «подтверждаю план от ДД.ММ.ГГГГ»
  - update snippet/status, thumbnail, optional playlist, #ayh_processed, ledger
  - расписание 12:00/18:00 MSK (кроме вт/пт); invalidPublishAt → retry without schedule
  - `--allow-ai` fallback для пустых description/tags (local stub)
- `list_channel_videos` через uploads playlist
- VideoResource: duration, processingStatus, is_short, never_published
- Playlist membership for «already styled»; vertical probe via ffprobe
- Audit fixes: fetch_channel_videos without hardcoded paths; analyze reads channel by default; final_aisie_plan/hooks metadata; duration match Shorts tie-break

## 0.1.0

- OAuth Device Flow (real + stub), encrypted token store
- Resumable upload, publish/schedule/delete, thumbnails
- Playlists create/add/delete, comments + moderation, captions
- Calendar, quota ledger, HTTP client, exit codes
- AI local stubs including chapters/translate/calendar
- CLI package commands/*
