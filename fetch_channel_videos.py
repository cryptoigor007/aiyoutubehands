"""Fetch all videos from the authenticated channel and store in SQLite DB."""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, "/Users/dreamstore/aiyoutubehands/src")

from aiyoutubehands.service_factory import build_youtube_service

DB_PATH = Path("/Users/dreamstore/aiyoutubehands/data/channel_videos.db")


def _passphrase() -> str:
    """Passphrase for the token vault. Never hardcode it — read from env."""
    from getpass import getpass

    value = os.environ.get("AYH_PASSPHRASE")
    if not value:
        value = getpass("Passphrase для хранилища токена: ")
    if not value:
        raise SystemExit("Пустая passphrase — аутентификация невозможна.")
    return value


def main():
    print("=" * 60)
    print("Загрузка всех видео с канала...")
    print("=" * 60)

    yt, client = build_youtube_service(passphrase=_passphrase())
    print("OK Аутентификация пройдена")

    # Get uploads playlist ID from channel object
    channel = yt.get_my_channel()
    playlist_id = channel.raw["contentDetails"]["relatedPlaylists"]["uploads"]
    print(f"Uploads playlist: {playlist_id}")

    # Fetch all video IDs from playlist
    print("\nЗагружаю список всех видео...")
    all_items = []
    page_token = None
    page = 0
    while True:
        page += 1
        params = {
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

    video_ids = [item["snippet"]["resourceId"]["videoId"] for item in all_items]
    print(f"\nВсего видео в плейлисте: {len(video_ids)}")

    # Fetch full details in batches
    print("\nЗагружаю полные характеристики видео...")
    BATCH = 50
    all_videos = []
    for i in range(0, len(video_ids), BATCH):
        batch = video_ids[i:i+BATCH]
        data = yt.client.get("videos", params={
            "part": "snippet,status,contentDetails,statistics",
            "id": ",".join(batch),
        })
        all_videos.extend(data.get("items", []))
        print(f"  Обработано {len(all_videos)}/{len(video_ids)}")

    print(f"\nВсего загружено характеристик: {len(all_videos)}")

    # Create database
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    cur.executescript("""
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
    """)
    conn.commit()
    print("\nБаза создана")

    # Clear old data
    cur.execute("DELETE FROM videos WHERE channel_type = 'old'")
    print("Старые записи удалены")

    # Insert all videos
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

        cur.execute("""
            INSERT OR REPLACE INTO videos
            (video_id, title, description, published_at, category_id, tags,
             privacy_status, view_count, like_count, comment_count,
             duration, definition, caption_count, thumbnails,
             channel_id, channel_title, channel_type, fetched_at, raw_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
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
            int(content.get("captionCount", 0)),
            str(thumbnails) if thumbnails else "",
            snippet.get("channelId", ""),
            snippet.get("channelTitle", ""),
            "old",
            fetched_at,
            str(item)
        ))
        inserted += 1

    conn.commit()
    print(f"\nOK Вставлено {inserted} видео в БД: {DB_PATH}")

    # Summary
    cur.execute("SELECT COUNT(*) FROM videos WHERE channel_type='old'")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM videos WHERE privacy_status='private'")
    private = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM videos WHERE privacy_status='public'")
    public = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM videos WHERE privacy_status='unlisted'")
    unlisted = cur.fetchone()[0]
    cur.execute("SELECT title, video_id, published_at FROM videos ORDER BY published_at DESC LIMIT 5")
    newest = cur.fetchall()

    print(f"\n{'='*60}")
    print(f"ИТОГО в базе: {total}")
    print(f"   Public: {public} | Private: {private} | Unlisted: {unlisted}")
    print(f"{'='*60}")
    print(f"\nПоследние 5 видео:")
    for title, vid, pub in newest:
        print(f"   {vid} [{pub}]: {title[:70]}")

    # Show all privacy statuses for reference
    cur.execute("SELECT privacy_status, COUNT(*) FROM videos GROUP BY privacy_status")
    print(f"\n{'='*60}")
    print("Распределение по статусам:")
    for status, count in cur.fetchall():
        print(f"   {status}: {count}")

    conn.close()
    client.close()
    print("\nГотово!")


if __name__ == "__main__":
    main()
