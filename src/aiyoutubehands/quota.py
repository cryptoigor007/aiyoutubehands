"""Quota engine, ledger and projection."""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from aiyoutubehands.logging import get_logger

log = get_logger(__name__)


class QuotaError(Exception):
    """Quota exceeded or ledger error."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "QUOTA_ERROR",
        action: str = "Дождитесь сброса квоты или используйте --force-quota",
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.action = action
        self.retryable = retryable


class QuotaLedger:
    """SQLite ledger of quota units consumed today."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    day TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    units INTEGER NOT NULL,
                    ts INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ledger_day ON ledger(day)"
            )

    @staticmethod
    def _today() -> str:
        # YouTube resets the daily quota at midnight Pacific Time, not UTC.
        # Using UTC makes the ledger report "fresh" quota during the 03:00-10:00
        # MSK window (07:00-14:00 UTC) when YouTube has already reset.
        return datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")

    def record(self, operation: str, units: int) -> None:
        day = self._today()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO ledger (day, operation, units, ts) VALUES (?, ?, ?, ?)",
                (day, operation, units, int(time.time())),
            )
        log.info("quota_recorded", operation=operation, units=units, day=day)

    def total_today(self) -> int:
        day = self._today()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(units), 0) AS total FROM ledger WHERE day = ?",
                (day,),
            ).fetchone()
        return int(row["total"])


class QuotaEngine:
    """Check / consume / project daily quota."""

    def __init__(
        self,
        db_path: Path | str,
        daily_limit: int = 10000,
        force_quota: bool = False,
    ) -> None:
        self.ledger = QuotaLedger(db_path)
        self.daily_limit = daily_limit
        self.force_quota = force_quota

    def used_today(self) -> int:
        return self.ledger.total_today()

    def remaining(self) -> int:
        return max(0, self.daily_limit - self.used_today())

    def check(self, units: int) -> None:
        if self.force_quota:
            return
        used = self.used_today()
        if used + units > self.daily_limit:
            raise QuotaError(
                f"Квота будет превышена: used={used}, need={units}, limit={self.daily_limit}",
                code="QUOTA_EXCEEDED",
                action="Дождитесь сброса или передайте --force-quota",
                retryable=False,
            )

    def consume(self, operation: str, units: int) -> None:
        self.check(units)
        self.ledger.record(operation, units)

    def project(self, operations: list[tuple[str, int]]) -> dict[str, Any]:
        extra = sum(u for _, u in operations)
        used = self.used_today()
        total = used + extra
        return {
            "used_today": used,
            "extra": extra,
            "projected_total": total,
            "daily_limit": self.daily_limit,
            "would_exceed": total > self.daily_limit and not self.force_quota,
            "remaining_after": max(0, self.daily_limit - total),
        }
