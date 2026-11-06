from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..models import Character, Draft
from ..services import drafts as svc
from ..services.queue import kick
from .characters import character_out, load_character
from .deps import ActiveUser, CtxDep, Session

router = APIRouter(prefix="/api")


async def load_draft(s, user, did: int) -> Draft:
    d = await s.get(Draft, did)
    if d is None or d.user_id != user.id:
        raise HTTPException(404, "not_found")
    return d


@router.get("/drafts")
async def list_drafts(u: ActiveUser, s: Session, ctx: CtxDep, status: str | None = None,
                      character_id: int | None = None, from_ms: int | None = Query(None),
                      to_ms: int | None = Query(None)) -> list[dict]:
    statuses = [x for x in status.split(",") if x] if status else None
    rows = await svc.list_drafts(s, u.id, statuses, character_id, from_ms, to_ms)
    chars: dict[int, Character] = {}
    out = []
    for d in rows:
        if d.character_id not in chars:
            chars[d.character_id] = await s.get(Character, d.character_id)
        out.append(await svc.draft_out(ctx, s, d, chars[d.character_id]))
    return out


@router.get("/drafts/{did}")
async def get_draft(did: int, u: ActiveUser, s: Session, ctx: CtxDep) -> dict:
    return await svc.draft_out(ctx, s, await load_draft(s, u, did))


class GenerateIn(BaseModel):
    trend: str | None = Field(None, max_length=500)


@router.post("/characters/{cid}/generate")
async def generate_now(cid: int, body: GenerateIn, u: ActiveUser, s: Session, ctx: CtxDep) -> dict:
    ch = await load_character(s, u, cid)
    if ch.status != "ready":
        raise HTTPException(400, "character_not_ready")
    d = await svc.generate_now(s, ch, body.trend)
    await s.commit()
    kick(ctx)
    return await svc.draft_out(ctx, s, d, ch)


class ScheduleIn(BaseModel):
    times: list[str] = Field(min_length=0, max_length=6)
    days: list[int] = Field(default_factory=lambda: list(range(7)))
    tz: str = Field("UTC", max_length=64)
    lead_hours: int = Field(6, ge=1, le=48)


class SettingsIn(BaseModel):
    schedule: ScheduleIn | None = None
    slides_max: int | None = Field(None, ge=1, le=5)
    ai_disclosure: bool | None = None
    disclosure_text: str | None = Field(None, max_length=80)
    trend: str | None = Field(None, max_length=500)
    autopilot: bool | None = None


@router.patch("/characters/{cid}/settings")
async def patch_settings(cid: int, body: SettingsIn, u: ActiveUser, s: Session, ctx: CtxDep) -> dict:
    import re

    from ..services.schedule import zone
    ch = await load_character(s, u, cid)
    if body.schedule is not None:
        sc = body.schedule
        times = sorted({t for t in sc.times if re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t)})
        if zone(sc.tz).key != sc.tz:
            raise HTTPException(400, "bad_timezone")
        ch.schedule = {"times": times, "days": sorted({d for d in sc.days if 0 <= d <= 6}), "tz": sc.tz,
                       "lead_hours": sc.lead_hours}
    for f in ("slides_max", "ai_disclosure", "disclosure_text", "trend"):
        v = getattr(body, f)
        if v is not None:
            setattr(ch, f, v)
    if body.autopilot is not None:
        from ..services import autopilot
        from ..services.approval import ActionError
        try:
            await autopilot.set_autopilot(ctx, s, ch, body.autopilot, by_owner=u.id in ctx.settings.admin_id_set)
        except ActionError as e:
            raise HTTPException(400, e.code) from e
    await s.commit()
    return await character_out(ctx, s, ch)


# ---------- review actions ----------

def _action_error(e) -> HTTPException:
    return HTTPException(404 if e.code == "not_found" else 400, e.code)


async def _act(ctx, s, u, did: int, fn) -> dict:
    from ..services.approval import ActionError
    d = await load_draft(s, u, did)
    ch = await s.get(Character, d.character_id)
    try:
        await fn(d, ch)
    except ActionError as e:
        raise _action_error(e) from e
    await s.commit()
    return await svc.draft_out(ctx, s, d, ch)


@router.post("/drafts/{did}/approve")
async def approve(did: int, u: ActiveUser, s: Session, ctx: CtxDep) -> dict:
    from ..services import approval
    return await _act(ctx, s, u, did, lambda d, ch: approval.approve(ctx, s, d, ch))


@router.post("/drafts/{did}/unschedule")
async def unschedule(did: int, u: ActiveUser, s: Session, ctx: CtxDep) -> dict:
    from ..services import approval
    return await _act(ctx, s, u, did, lambda d, ch: approval.unschedule(s, d))


@router.post("/drafts/{did}/skip")
async def skip(did: int, u: ActiveUser, s: Session, ctx: CtxDep) -> dict:
    from ..services import approval
    return await _act(ctx, s, u, did, lambda d, ch: approval.skip(s, d, ch))


class RegenIn(BaseModel):
    what: str = Field("all", pattern="^(all|images)$")
    slides: list[int] | None = None


@router.post("/drafts/{did}/regenerate")
async def regenerate(did: int, body: RegenIn, u: ActiveUser, s: Session, ctx: CtxDep) -> dict:
    from ..services import approval
    return await _act(ctx, s, u, did, lambda d, ch: approval.regenerate(ctx, s, d, ch, body.what == "images",
                                                                          body.slides))


class EditIn(BaseModel):
    caption: str | None = Field(None, max_length=2200)
    hashtags: list[str] | None = Field(None, max_length=30)
    order: list[int] | None = Field(None, max_length=10)


@router.patch("/drafts/{did}")
async def edit(did: int, body: EditIn, u: ActiveUser, s: Session, ctx: CtxDep) -> dict:
    from ..services import approval

    async def fn(d, ch):
        await approval.edit(d, body.caption, body.hashtags, body.order)
    return await _act(ctx, s, u, did, fn)


# ---------- calendar ----------

@router.get("/calendar")
async def calendar(u: ActiveUser, s: Session, ctx: CtxDep, from_ms: int, to_ms: int,
                   character_id: int | None = None) -> dict:
    """Drafts in the range plus schedule slots that don't have a draft yet ("planned")."""
    from sqlalchemy import select

    from ..services.schedule import slots
    if to_ms - from_ms > 62 * 86_400_000:
        raise HTTPException(400, "range_too_long")
    rows = await svc.list_drafts(s, u.id, None, character_id, from_ms, to_ms)
    q = select(Character).where(Character.user_id == u.id, Character.archived.is_(False),
                                Character.status == "ready")
    if character_id:
        q = q.where(Character.id == character_id)
    chars = {c.id: c for c in (await s.execute(q)).scalars()}
    taken = {(d.character_id, d.slot_ms) for d in rows}
    from ..services.users import now_ms
    planned = [{"character": {"id": c.id, "name": c.name, "handle": c.handle}, "slot_ms": ms}
               for c in chars.values() for ms in slots(c.schedule, max(from_ms, now_ms()), to_ms)
               if (c.id, ms) not in taken]
    items = []
    for d in rows:
        if d.status == "skipped":
            continue
        ch = chars.get(d.character_id) or await s.get(Character, d.character_id)
        first = d.slides[0]["key"] if d.slides else None
        items.append({"id": d.id, "character": {"id": ch.id, "name": ch.name, "handle": ch.handle},
                      "slot_ms": d.slot_ms, "status": d.status, "rubric": d.rubric, "idea": d.idea,
                      "thumb": ctx.storage.url(first) if first else None})
    return {"drafts": items, "planned": sorted(planned, key=lambda x: x["slot_ms"])}
