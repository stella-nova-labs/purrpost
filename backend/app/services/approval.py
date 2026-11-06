"""Actions on a draft, shared by the bot buttons and the Mini App."""

from __future__ import annotations

import html
import re

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Character, Draft
from .bot_links import draft_for_message, remember_message
from .drafts import REVIEW_STATUSES, approval_buttons, draft_message, slot_text
from .queue import enqueue, kick
from .users import now_ms


class ActionError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


async def _get(s: AsyncSession, user_id: int, draft_id: int) -> tuple[Draft, Character]:
    d = await s.get(Draft, draft_id)
    if d is None or d.user_id != user_id:
        raise ActionError("not_found")
    return d, await s.get(Character, d.character_id)


async def approve(ctx, s: AsyncSession, d: Draft, ch: Character) -> None:
    if d.status not in REVIEW_STATUSES:
        raise ActionError("wrong_status")
    d.status, d.approved_ms = "scheduled", now_ms()
    ch.approved_streak += 1
    from .autopilot import after_approval
    await after_approval(ctx, s, ch)


async def unschedule(s: AsyncSession, d: Draft) -> None:
    if d.status != "scheduled":
        raise ActionError("wrong_status")
    d.status, d.approved_ms = ("pending_review" if d.qa_ok else "needs_review"), None


async def skip(s: AsyncSession, d: Draft, ch: Character) -> None:
    if d.status not in (*REVIEW_STATUSES, "scheduled", "failed"):
        raise ActionError("wrong_status")
    d.status = "skipped"
    ch.approved_streak = 0


async def regenerate(ctx, s: AsyncSession, d: Draft, ch: Character, images_only: bool,
                     slides: list[int] | None = None) -> None:
    if d.status not in (*REVIEW_STATUSES, "scheduled", "failed"):
        raise ActionError("wrong_status")
    if images_only and not d.slides:
        images_only = False  # nothing to keep: the plan itself failed
    ch.approved_streak = 0
    n = now_ms()
    if images_only:
        d.status, d.error, d.approved_ms = "generating", None, None
        await enqueue(s, "regen_images", d.user_id, character_id=ch.id, draft_id=d.id,
                      payload={"slides": slides}, dedupe_key=f"regen:{d.id}")
    else:
        d.status, d.error, d.approved_ms, d.slides, d.caption_edited = "generating", None, None, [], False
        d.idea = d.caption = d.alt_text = d.summary = ""
        d.hashtags = []
        await enqueue(s, "plan", d.user_id, character_id=ch.id, draft_id=d.id, dedupe_key=f"plan:{d.id}:{n}")
    kick(ctx)


def _clean_tags(tags: list[str]) -> list[str]:
    out: list[str] = []
    for t in tags:
        t = "#" + re.sub(r"[^\w]", "", t.lstrip("#"))
        if len(t) > 1 and t.lower() not in (x.lower() for x in out):
            out.append(t)
    return out[:30]


async def edit(d: Draft, caption: str | None = None, hashtags: list[str] | None = None,
               order: list[int] | None = None) -> None:
    if d.status not in (*REVIEW_STATUSES, "scheduled"):
        raise ActionError("wrong_status")
    if caption is not None:
        caption = caption.strip()
        if not caption or len(caption) > 2000:
            raise ActionError("bad_caption")
        d.caption, d.caption_edited = caption, True
    if hashtags is not None:
        d.hashtags = _clean_tags(hashtags)
    if order is not None:
        if sorted(order) != list(range(len(d.slides))):
            raise ActionError("bad_order")
        d.slides = [d.slides[i] for i in order]


# ---------- bot ----------

async def handle_callback(ctx, user_id: int, data: str) -> str:
    """Button press under a draft message. Returns the text to show (toast or appended line)."""
    try:
        prefix, action, raw_id = data.split(":")
        draft_id = int(raw_id)
    except ValueError:
        return "Неизвестная кнопка"
    if prefix != "d":
        return "Неизвестная кнопка"
    async with ctx.db.sessions() as s:
        try:
            d, ch = await _get(s, user_id, draft_id)
            if action == "ok":
                await approve(ctx, s, d, ch)
                msg = f"✅ Запланировано на {slot_text(d, ch)}"
            elif action == "skip":
                await skip(s, d, ch)
                msg = "🗑 Пропущено"
            elif action == "regen":
                await regenerate(ctx, s, d, ch, images_only=False)
                msg = "🔄 Делаю пост заново, пришлю новый черновик"
            elif action == "img":
                await regenerate(ctx, s, d, ch, images_only=True)
                msg = "🖼 Перерисовываю картинки, подпись останется"
            elif action == "edit":
                if d.status not in (*REVIEW_STATUSES, "scheduled"):
                    raise ActionError("wrong_status")
                mid = await ctx.notifier.send(user_id, "✏️ Ответьте на это сообщение новым текстом подписи "
                                                       "(хештеги и пометка об ИИ добавятся сами).")
                await remember_message(s, user_id, mid, d.id)
                msg = "Жду новую подпись ответом на сообщение"
            else:
                return "Неизвестная кнопка"
            await s.commit()
            return msg
        except ActionError as e:
            return {"not_found": "Черновик не найден", "wrong_status": "С этим черновиком уже что-то сделали"}.get(
                e.code, e.code)


async def handle_reply(ctx, user_id: int, reply_to_message_id: int, text: str) -> str | None:
    """A reply to a draft message: the new caption. Returns None if the message isn't about a draft."""
    async with ctx.db.sessions() as s:
        draft_id = await draft_for_message(s, user_id, reply_to_message_id)
        if draft_id is None:
            return None
        try:
            d, ch = await _get(s, user_id, draft_id)
            await edit(d, caption=text)
        except ActionError as e:
            return {"bad_caption": "Подпись пустая или длиннее 2000 символов",
                    "wrong_status": "Этот черновик уже нельзя изменить"}.get(e.code, e.code)
        await s.commit()
        mid = await ctx.notifier.send(user_id, "Подпись обновлена:\n\n" + draft_message(d, ch),
                                      approval_buttons(d) if d.status in REVIEW_STATUSES else None)
        await remember_message(s, user_id, mid, d.id)
        await s.commit()
        return "ok"


def escape(t: str) -> str:
    return html.escape(t)
