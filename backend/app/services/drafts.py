"""Drafts as the user sees them: serialization, bot messages, edits."""

from __future__ import annotations

import html
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Character, Draft
from .notify import Button
from .pipeline import final_caption
from .queue import busy
from .schedule import create_draft, next_free_slot, zone

REVIEW_STATUSES = ("pending_review", "needs_review")

WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
MONTHS = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]


def slot_text(d: Draft, ch: Character) -> str:
    dt = datetime.fromtimestamp(d.slot_ms / 1000, zone(ch.schedule.get("tz", "UTC")))
    return f"{WEEKDAYS[dt.weekday()]}, {dt.day} {MONTHS[dt.month - 1]}, {dt:%H:%M} ({ch.schedule.get('tz', 'UTC')})"


async def draft_out(ctx, s: AsyncSession, d: Draft, ch: Character | None = None) -> dict:
    ch = ch or await s.get(Character, d.character_id)
    return {
        "id": d.id, "character": {"id": ch.id, "name": ch.name, "handle": ch.handle},
        "slot_ms": d.slot_ms, "rubric": d.rubric, "trend": d.trend, "idea": d.idea, "caption": d.caption,
        "hashtags": d.hashtags, "alt_text": d.alt_text, "status": d.status, "qa_ok": d.qa_ok, "error": d.error,
        "slides": [{"index": i, "scene": sl["scene"], "url": ctx.storage.url(sl["key"]), "ok": sl.get("ok", False),
                    "issues": (sl.get("qa") or {}).get("issues", [])} for i, sl in enumerate(d.slides or [])],
        "final_caption": final_caption(d, ch), "busy": await busy(s, draft_id=d.id),
        "approved_ms": d.approved_ms, "published_ms": d.published_ms, "created_ms": d.created_ms,
    }


def approval_buttons(d: Draft) -> list[list[Button]]:
    return [
        [Button("✅ Опубликовать по расписанию", f"d:ok:{d.id}")],
        [Button("🔄 Всё заново", f"d:regen:{d.id}"), Button("🖼 Картинки", f"d:img:{d.id}")],
        [Button("✏️ Подпись", f"d:edit:{d.id}"), Button("🗑 Пропустить", f"d:skip:{d.id}")],
    ]


def draft_message(d: Draft, ch: Character) -> str:
    head = f"<b>{html.escape(ch.name)}</b> · черновик на {slot_text(d, ch)}"
    if d.rubric:
        head += f"\nРубрика: {html.escape(d.rubric)}"
    warn = ""
    if not d.qa_ok:
        issues = [i for sl in d.slides for i in (sl.get("qa") or {}).get("issues", [])][:4]
        warn = "\n\n⚠️ <b>Нужна проверка:</b> QA не пропустил часть картинок" + (
            ": " + html.escape("; ".join(issues)) if issues else "")
    return f"{head}{warn}\n\n{html.escape(final_caption(d, ch))}"


async def notify_draft(ctx, s: AsyncSession, d: Draft, ch: Character) -> None:
    """Send a draft for approval. On autopilot nothing is sent now: the bot reports the published post."""
    if d.status not in REVIEW_STATUSES:
        return
    photos = [await ctx.storage.get(sl["key"]) for sl in d.slides]
    mid = await ctx.notifier.send_album(d.user_id, photos, draft_message(d, ch), approval_buttons(d))
    from .bot_links import remember_message
    await remember_message(s, d.user_id, mid, d.id)
    await s.commit()


async def generate_now(s: AsyncSession, ch: Character, trend: str | None) -> Draft:
    slot = await next_free_slot(s, ch)
    d = await create_draft(s, ch, slot, trend)
    assert d is not None
    return d


async def list_drafts(s: AsyncSession, user_id: int, statuses: list[str] | None, character_id: int | None,
                      from_ms: int | None = None, to_ms: int | None = None) -> list[Draft]:
    q = select(Draft).where(Draft.user_id == user_id)
    if statuses:
        q = q.where(Draft.status.in_(statuses))
    if character_id:
        q = q.where(Draft.character_id == character_id)
    if from_ms is not None:
        q = q.where(Draft.slot_ms >= from_ms)
    if to_ms is not None:
        q = q.where(Draft.slot_ms < to_ms)
    return list((await s.execute(q.order_by(Draft.slot_ms))).scalars())
