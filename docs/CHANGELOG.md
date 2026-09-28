# Changelog

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
