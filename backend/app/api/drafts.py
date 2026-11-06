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
    await s.commit()
    return await character_out(ctx, s, ch)
