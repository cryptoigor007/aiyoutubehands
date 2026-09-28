"""Ledger of processed videos (SQLite) + #ayh_processed marker helper."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from aiyoutubehands.config import get_config_dir
from aiyoutubehands.logging import get_logger

log = get_logger(__name__)

MARKER = "#ayh_processed"


class ProcessedLedger:
    """Local SQLite ledger of successfully post-processed video IDs."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            db_path = get_config_dir() / "processed.db"
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS processed (
                    video_id TEXT PRIMARY KEY,
                    folder_name TEXT,
                    title TEXT,
                    ts INTEGER NOT NULL,
                    run_id TEXT
                )
                """
            )

    def is_processed(self, video_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM processed WHERE video_id = ?", (video_id,)).fetchone()
        return row is not None

    def all_ids(self) -> set[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT video_id FROM processed").fetchall()
        return {str(r["video_id"]) for r in rows}

    def record(
        self,
        video_id: str,
        *,
        folder_name: str = "",
        title: str = "",
        run_id: str = "",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO processed (video_id, folder_name, title, ts, run_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (video_id, folder_name, title, int(time.time()), run_id),
            )
        log.info("ledger_record", video_id=video_id, folder=folder_name)

    @staticmethod
    def append_marker(description: str) -> str:
        """Append hidden marker to description if not already present."""
        desc = description or ""
        if MARKER in desc:
            return desc
        if desc and not desc.endswith("\n"):
            desc += "\n"
        return desc + f"\n{MARKER}"
