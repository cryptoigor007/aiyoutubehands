"""Propose publish slots for Shorts: 12:00 and 18:00 Europe/Moscow, no Tue/Fri."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiyoutubehands.logging import get_logger
from aiyoutubehands.models.youtube import VideoResource

log = get_logger(__name__)

MSK = ZoneInfo("Europe/Moscow")
# Monday=0 ... Sunday=6; skip Tuesday=1, Friday=4
SKIP_WEEKDAYS = {1, 4}
SLOT_HOURS = (12, 18)
HORIZON_DAYS = 30


def _slot_datetimes(
    start: datetime | None = None,
    horizon_days: int = HORIZON_DAYS,
) -> list[datetime]:
    """Generate candidate slots in MSK."""
    now = start or datetime.now(MSK)
    if now.tzinfo is None:
        now = now.replace(tzinfo=MSK)
    else:
        now = now.astimezone(MSK)

    slots: list[datetime] = []
    day = now.date()
    end = day + timedelta(days=horizon_days)
    while day <= end:
        if day.weekday() not in SKIP_WEEKDAYS:
            for hour in SLOT_HOURS:
                dt = datetime(day.year, day.month, day.day, hour, 0, 0, tzinfo=MSK)
                if dt > now:
                    slots.append(dt)
        day += timedelta(days=1)
    return slots


def propose_slots(
    videos: list[VideoResource | None],
    *,
    occupied: set[str] | None = None,
    horizon_days: int = HORIZON_DAYS,
    now: datetime | None = None,
) -> list[str | None]:
    """Return ISO8601 publishAt (UTC Z) or None when schedule unavailable.

    publishAt is only valid when privacy=private AND video was never published.
    """
    occupied = set(occupied or [])
    slots = _slot_datetimes(start=now, horizon_days=horizon_days)
    slot_idx = 0
    result: list[str | None] = []

    for video in videos:
        if video is None:
            result.append(None)
            continue
        if not video.never_published():
            result.append(None)  # schedule unavailable
            continue
        # Find next free slot
        chosen: str | None = None
        while slot_idx < len(slots):
            dt = slots[slot_idx]
            slot_idx += 1
            iso = dt.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
            if iso in occupied:
                continue
            chosen = iso
            occupied.add(iso)
            break
        result.append(chosen)

    return result


def format_slot_local(iso_utc: str | None) -> str:
    """Human-readable MSK string for plan table."""
    if not iso_utc:
        return "расписание недоступно"
    try:
        dt = datetime.fromisoformat(iso_utc.replace("Z", "+00:00")).astimezone(MSK)
        return dt.strftime("%d.%m.%Y %H:%M MSK")
    except ValueError:
        return iso_utc
