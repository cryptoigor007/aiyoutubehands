"""Fetch all videos from the authenticated channel and store in SQLite DB.

Standalone utility (not part of ``ayh process``). Uses XDG state dir by default.

Usage::

    PYTHONPATH=src python3 fetch_channel_videos.py
    AYH_CHANNEL_DB=/tmp/videos.db PYTHONPATH=src python3 fetch_channel_videos.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# Prefer installed / PYTHONPATH package; no hardcoded machine paths.
_REPO_SRC = Path(__file__).resolve().parent / "src"
if _REPO_SRC.is_dir() and str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

from aiyoutubehands.config import get_state_dir  # noqa: E402
from aiyoutubehands.service_factory import build_youtube_service  # noqa: E402


def _default_db_path() -> Path:
    env = os.environ.get("AYH_CHANNEL_DB")
    if env:
        return Path(env).expanduser()
    return get_state_dir() / "channel_videos.db"


def _passphrase() -> str:
    """Passphrase for the token vault. Never hardcode it — read from env."""
    from getpass import getpass

    value = os.environ.get("AYH_PASSPHRASE")
    if not value:
        value = getpass("Passphrase для хранилища токена: ")
    if not value:
        raise SystemExit("Пустая passphrase — аутентификация невозможна.")
    return value


def main() -> None:
    db_path = _default_db_path()
    print("=" * 60)
    print("Загрузка всех видео с канала...")
    print(f"DB: {db_path}")
    print("=" * 60)

    yt, client = build_youtube_service(passphrase=_passphrase())
    print("OK Аутентификация пройдена")

    try:
        channel = yt.get_my_channel()
        if not hasattr(channel, "raw"):
            raise SystemExit("Не удалось получить канал")
        playlist_id = channel.raw["contentDetails"]["relatedPlaylists"]["uploads"]
        print(f"Uploads playlist: {playlist_id}")

        print("\nЗагружаю список всех видео...")
        all_items: list[dict] = []
        page_token = None
        page = 0
        while True:
            page += 1
            params: dict = {
                "part": "snippet,contentDetails",
                "playlistId": playlist_id,
                "maxResults": 50,
            }
            if page_token:
                params["pageToken"] = page_token
            data = yt.client.get("playlistItems", params=params)
            items = data.get("items", [])
            all_items.extend(items)
            print(f"  Страница {page}: {len(items)} видео (всего: {len(all_items)})")
            page_token = data.get("nextPageToken")
            if not page_token:
                break

        video_ids = [
            item["snippet"]["resourceId"]["videoId"] for item in all_items
        ]
        print(f"\nВсего видео в плейлисте: {len(video_ids)}")

        print("\nЗагружаю полные характеристики видео...")
        batch_size = 50
        all_videos: list[dict] = []
        for i in range(0, len(video_ids), batch_size):
            batch = video_ids[i : i + batch_size]
            data = yt.client.get(
                "videos",
                params={
                    "part": "snippet,status,contentDetails,statistics",
                    "id": ",".join(batch),
                },
            )
            all_videos.extend(data.get("items", []))
            print(f"  Обработано {len(all_videos)}/{len(video_ids)}")

        print(f"\nВсего загружено характеристик: {len(all_videos)}")

        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS videos (
                video_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT,
                published_at TEXT,
                category_id TEXT,
                tags TEXT,
                privacy_status TEXT,
                view_count INTEGER DEFAULT 0,
                like_count INTEGER DEFAULT 0,
                comment_count INTEGER DEFAULT 0,
                duration TEXT,
                definition TEXT,
                caption_count INTEGER DEFAULT 0,
                thumbnails TEXT,
                channel_id TEXT,
                channel_title TEXT,
                channel_type TEXT NOT NULL DEFAULT 'old',
                fetched_at TEXT NOT NULL,
                raw_data TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_videos_channel_type ON videos(channel_type);
            CREATE INDEX IF NOT EXISTS idx_videos_published ON videos(published_at);
            CREATE INDEX IF NOT EXISTS idx_videos_title ON videos(title COLLATE NOCASE);
            """
        )
        conn.commit()
        print("\nБаза создана")

        cur.execute("DELETE FROM videos WHERE channel_type = 'old'")
        print("Старые записи удалены")

        fetched_at = datetime.now(timezone.utc).isoformat()
        inserted = 0
        for item in all_videos:
            video_id = item["id"]
            snippet = item.get("snippet", {})
            status = item.get("status", {})
            content = item.get("contentDetails", {})
            stats = item.get("statistics", {})
            tags = snippet.get("tags", []) or []
            thumbnails = snippet.get("thumbnails", {}) or {}

            cur.execute(
                """
                INSERT OR REPLACE INTO videos
                (video_id, title, description, published_at, category_id, tags,
                 privacy_status, view_count, like_count, comment_count,
                 duration, definition, caption_count, thumbnails,
                 channel_id, channel_title, channel_type, fetched_at, raw_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    video_id,
                    snippet.get("title", ""),
                    snippet.get("description", ""),
                    snippet.get("publishedAt", ""),
                    snippet.get("categoryId", ""),
                    ",".join(tags) if tags else "",
                    status.get("privacyStatus", ""),
                    int(stats.get("viewCount", 0)),
                    int(stats.get("likeCount", 0)),
                    int(stats.get("commentCount", 0)),
                    content.get("duration", ""),
                    content.get("definition", ""),
                    int(content.get("captionCount", 0) or 0),
                    str(thumbnails) if thumbnails else "",
                    snippet.get("channelId", ""),
                    snippet.get("channelTitle", ""),
                    "old",
                    fetched_at,
                    str(item),
                ),
            )
            inserted += 1

        conn.commit()
        print(f"\nOK Вставлено {inserted} видео в БД: {db_path}")

        cur.execute("SELECT COUNT(*) FROM videos WHERE channel_type='old'")
        total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM videos WHERE privacy_status='private'")
        private = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM videos WHERE privacy_status='public'")
        public = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM videos WHERE privacy_status='unlisted'")
        unlisted = cur.fetchone()[0]
        cur.execute(
            "SELECT title, video_id, published_at FROM videos "
            "ORDER BY published_at DESC LIMIT 5"
        )
        newest = cur.fetchall()

        print(f"\n{'=' * 60}")
        print(f"ИТОГО в базе: {total}")
        print(f"   Public: {public} | Private: {private} | Unlisted: {unlisted}")
        print(f"{'=' * 60}")
        print("\nПоследние 5 видео:")
        for title, vid, pub in newest:
            print(f"   {vid} [{pub}]: {title[:70]}")

        cur.execute(
            "SELECT privacy_status, COUNT(*) FROM videos GROUP BY privacy_status"
        )
        print(f"\n{'=' * 60}")
        print("Распределение по статусам:")
        for st, count in cur.fetchall():
            print(f"   {st}: {count}")

        conn.close()
        print("\nГотово!")
    finally:
        client.close()


if __name__ == "__main__":
    main()
