"""Posting schedule: which slots exist, and the planner that creates one draft per slot."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Character, Draft
from .queue import enqueue, kick
from .users import now_ms

log = logging.getLogger("purrpost.schedule")


def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def slots(schedule: dict, from_ms: int, to_ms: int) -> list[int]:
    """Publish times (ms) in [from_ms, to_ms). Times are wall-clock in the audience's time zone, so 18:00 stays
    18:00 across DST changes."""
    tz = zone(schedule.get("tz", "UTC"))
    days = set(schedule.get("days", range(7)))
    times = []
    for t in schedule.get("times", []):
        try:
            hh, mm = (int(x) for x in t.split(":"))
            times.append((hh, mm))
        except ValueError:
            continue
    start = datetime.fromtimestamp(from_ms / 1000, tz).date() - timedelta(days=1)
    end = datetime.fromtimestamp(to_ms / 1000, tz).date() + timedelta(days=1)
    out = []
    d = start
    while d <= end:
        if d.weekday() in days:
            for hh, mm in times:
                ms = int(datetime(d.year, d.month, d.day, hh, mm, tzinfo=tz).timestamp() * 1000)
                if from_ms <= ms < to_ms:
                    out.append(ms)
        d += timedelta(days=1)
    return sorted(set(out))


def rubric_for(ch: Character, slot_ms: int) -> dict | None:
    """The rubric of the slot's weekday; otherwise rubrics without a day take turns."""
    wd = datetime.fromtimestamp(slot_ms / 1000, zone(ch.schedule.get("tz", "UTC"))).weekday()
    rubrics = ch.rubrics or []
    day = [r for r in rubrics if r.get("weekday") == wd]
    if day:
        return day[0]
    free = [r for r in rubrics if r.get("weekday") is None]
    if free:
        return free[(slot_ms // 86_400_000) % len(free)]
    return None


async def create_draft(s: AsyncSession, ch: Character, slot_ms: int, trend: str | None = None) -> Draft | None:
    """Create the draft for a slot and queue its generation. Returns None if the slot already has a draft."""
    r = rubric_for(ch, slot_ms)
    d = Draft(character_id=ch.id, user_id=ch.user_id, slot_ms=slot_ms, rubric=(r or {}).get("title", ""),
              trend=ch.trend if trend is None else trend, status="generating", created_ms=now_ms())
    try:
        async with s.begin_nested():
            s.add(d)
    except IntegrityError:
        return None
    await enqueue(s, "plan", ch.user_id, character_id=ch.id, draft_id=d.id, dedupe_key=f"plan:{d.id}")
    return d


async def plan(ctx, now: int | None = None) -> int:
    """Worker step: for every ready character, create drafts for slots within its lead time."""
    now = now or now_ms()
    created = 0
    async with ctx.db.sessions() as s:
        chars = (await s.execute(select(Character).where(Character.status == "ready",
                                                         Character.archived.is_(False)))).scalars().all()
        for ch in chars:
            lead = int(ch.schedule.get("lead_hours", 6)) * 3600_000
            for slot in slots(ch.schedule, now, now + lead):
                if await create_draft(s, ch, slot):
                    created += 1
        await s.commit()
    if created:
        log.info("planned %d drafts", created)
        kick(ctx)
    return created


async def next_free_slot(s: AsyncSession, ch: Character, now: int | None = None) -> int:
    """The nearest schedule slot (at least 15 minutes ahead) without a draft; for "make a post now"."""
    now = now or now_ms()
    taken = set((await s.execute(select(Draft.slot_ms).where(Draft.character_id == ch.id, Draft.slot_ms >= now)))
                .scalars())
    for slot in slots(ch.schedule, now + 15 * 60_000, now + 60 * 86_400_000):
        if slot not in taken:
            return slot
    return now + 3600_000  # no schedule at all: in an hour
