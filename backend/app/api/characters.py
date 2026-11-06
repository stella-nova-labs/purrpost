from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..models import Character, CharacterImage
from ..services import autopilot
from ..services import characters as svc
from ..services.queue import busy, kick, last_error
from ..services.templates import TEMPLATES
from .deps import ActiveUser, CtxDep, Session

router = APIRouter(prefix="/api")


async def load_character(s, user, cid: int) -> Character:
    """The character, if it belongs to this user (others get 404, not 403: no probing of ids)."""
    ch = await s.get(Character, cid)
    if ch is None or ch.user_id != user.id or ch.archived:
        raise HTTPException(404, "not_found")
    return ch


def _err(e: svc.CardError) -> HTTPException:
    return HTTPException(400, {"code": e.code, "items": e.detail})


def image_out(ctx, img: CharacterImage) -> dict:
    return {"id": img.id, "kind": img.kind, "url": ctx.storage.url(img.key), "batch": img.batch}


async def character_out(ctx, s, ch: Character, full: bool = True) -> dict:
    out = {
        "id": ch.id, "name": ch.name, "handle": ch.handle, "status": ch.status, "template": ch.template_slug,
        "autopilot": ch.autopilot, "approved_streak": ch.approved_streak, "avatar": None,
    }
    chosen = await s.get(CharacterImage, ch.chosen_image_id) if ch.chosen_image_id else None
    if chosen:
        out["avatar"] = ctx.storage.url(chosen.key)
    if not full:
        return out
    imgs = await svc.images(s, ch)
    jobs = await busy(s, character_id=ch.id)
    last = await last_error(s, ch.id)
    out.update({
        "card": {"name": ch.name, "handle": ch.handle, "personality": ch.personality, "pain": ch.pain,
                 "humor": ch.humor, "language": ch.language, "appearance": ch.appearance, "rubrics": ch.rubrics,
                 "stop_topics": ch.stop_topics, "notes": ch.notes},
        "appearance_text": ch.appearance_text, "chosen_image_id": ch.chosen_image_id,
        "lora_trigger": ch.lora_trigger, "has_lora": bool(ch.lora_url), "training_error": ch.training_error,
        "candidates": [image_out(ctx, i) for i in imgs if i.kind == "candidate"],
        "refs": [image_out(ctx, i) for i in imgs if i.kind == "ref"],
        "tests": [image_out(ctx, i) for i in imgs if i.kind == "test"],
        "busy": jobs, "min_refs": svc.MIN_REFS,
        "last_job": {"kind": last.kind, "status": last.status, "error": last.error} if last else None,
        "schedule": ch.schedule, "slides_max": ch.slides_max, "ai_disclosure": ch.ai_disclosure,
        "disclosure_text": ch.disclosure_text, "trend": ch.trend, "lore": ch.lore[-5:],
        "autopilot_streak": ctx.settings.autopilot_streak, "autopilot_unlocked": autopilot.unlocked(ctx, ch),
    })
    return out


@router.get("/templates")
async def templates(_: ActiveUser) -> list[dict]:
    return [{"slug": k, "name": v["name"], "handle": v["handle"], "personality": v["personality"],
             "notes": v["notes"]} for k, v in TEMPLATES.items()]


class SuggestIn(BaseModel):
    idea: str = Field(min_length=3, max_length=300)


@router.post("/characters/suggest")
async def suggest(body: SuggestIn, u: ActiveUser, s: Session, request_ctx: CtxDep) -> dict:
    from ..services.budget import BudgetExceeded
    try:
        return await svc.suggest(request_ctx, s, u, body.idea)
    except svc.CardError as e:
        raise _err(e) from e
    except BudgetExceeded as e:
        raise HTTPException(402, "budget_exceeded") from e


@router.get("/characters")
async def list_characters(u: ActiveUser, s: Session, ctx: CtxDep) -> list[dict]:
    rows = (await s.execute(select(Character).where(Character.user_id == u.id, Character.archived.is_(False))
                            .order_by(Character.id))).scalars().all()
    return [await character_out(ctx, s, ch, full=False) for ch in rows]


@router.post("/characters")
async def create_character(body: svc.Card, u: ActiveUser, s: Session, ctx: CtxDep) -> dict:
    try:
        ch = await svc.create(s, u, body)
    except svc.CardError as e:
        raise _err(e) from e
    await s.commit()
    return await character_out(ctx, s, ch)


@router.post("/characters/from-template/{slug}")
async def from_template(slug: str, u: ActiveUser, s: Session, ctx: CtxDep) -> dict:
    try:
        ch = await svc.create_from_template(s, u, slug)
    except svc.CardError as e:
        raise HTTPException(404, e.code) from e
    await svc.request_candidates(s, ch, 8, "")
    await s.commit()
    kick(ctx)
    return await character_out(ctx, s, ch)


@router.get("/characters/{cid}")
async def get_character(cid: int, u: ActiveUser, s: Session, ctx: CtxDep) -> dict:
    return await character_out(ctx, s, await load_character(s, u, cid))


@router.put("/characters/{cid}/card")
async def put_card(cid: int, body: svc.Card, u: ActiveUser, s: Session, ctx: CtxDep) -> dict:
    ch = await load_character(s, u, cid)
    try:
        await svc.update_card(s, ch, body)
    except svc.CardError as e:
        raise _err(e) from e
    await s.commit()
    return await character_out(ctx, s, ch)


class CandidatesIn(BaseModel):
    count: int = Field(8, ge=4, le=12)
    extra: str = Field("", max_length=400)


async def _enqueued(ctx, s, job, ch) -> dict:
    await s.commit()
    kick(ctx)
    return await character_out(ctx, s, ch)


@router.post("/characters/{cid}/candidates")
async def candidates(cid: int, body: CandidatesIn, u: ActiveUser, s: Session, ctx: CtxDep) -> dict:
    ch = await load_character(s, u, cid)
    return await _enqueued(ctx, s, await svc.request_candidates(s, ch, body.count, body.extra), ch)


class ChooseIn(BaseModel):
    image_id: int


@router.post("/characters/{cid}/choose")
async def choose(cid: int, body: ChooseIn, u: ActiveUser, s: Session, ctx: CtxDep) -> dict:
    ch = await load_character(s, u, cid)
    try:
        await svc.choose(s, ch, body.image_id)
        job = await svc.request_refsheet(s, ch, 16)
    except svc.CardError as e:
        raise _err(e) from e
    return await _enqueued(ctx, s, job, ch)


class RefsIn(BaseModel):
    count: int = Field(16, ge=10, le=20)


@router.post("/characters/{cid}/refsheet")
async def refsheet(cid: int, body: RefsIn, u: ActiveUser, s: Session, ctx: CtxDep) -> dict:
    ch = await load_character(s, u, cid)
    try:
        job = await svc.request_refsheet(s, ch, body.count)
    except svc.CardError as e:
        raise _err(e) from e
    return await _enqueued(ctx, s, job, ch)


@router.delete("/characters/{cid}/images/{image_id}")
async def delete_image(cid: int, image_id: int, u: ActiveUser, s: Session, ctx: CtxDep) -> dict:
    ch = await load_character(s, u, cid)
    try:
        await svc.delete_image(s, ch, image_id)
    except svc.CardError as e:
        raise _err(e) from e
    await s.commit()
    return await character_out(ctx, s, ch)


@router.post("/characters/{cid}/train")
async def train(cid: int, u: ActiveUser, s: Session, ctx: CtxDep) -> dict:
    ch = await load_character(s, u, cid)
    try:
        job = await svc.request_training(s, ch)
    except svc.CardError as e:
        raise _err(e) from e
    return await _enqueued(ctx, s, job, ch)


class ConfirmIn(BaseModel):
    ok: bool


@router.post("/characters/{cid}/confirm")
async def confirm(cid: int, body: ConfirmIn, u: ActiveUser, s: Session, ctx: CtxDep) -> dict:
    ch = await load_character(s, u, cid)
    try:
        await svc.confirm(ctx, s, ch, body.ok)
    except svc.CardError as e:
        raise _err(e) from e
    await s.commit()
    return await character_out(ctx, s, ch)


@router.delete("/characters/{cid}")
async def archive(cid: int, u: ActiveUser, s: Session) -> dict:
    ch = await load_character(s, u, cid)
    ch.archived = True
    await s.commit()
    return {"ok": True}
