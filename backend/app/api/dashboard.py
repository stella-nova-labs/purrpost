from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select

from ..models import Character, Draft, User
from ..services import autopilot, budget
from ..services.metrics import dashboard
from .characters import load_character
from .deps import ActiveUser, AdminUser, CtxDep, Session

router = APIRouter(prefix="/api")


@router.get("/dashboard")
async def get_dashboard(u: ActiveUser, s: Session, ctx: CtxDep, character_id: int | None = None) -> dict:
    if character_id:
        await load_character(s, u, character_id)
    out = await dashboard(ctx, s, u.id, character_id)
    out["budget"] = await budget.summary(s, u, ctx.settings)
    return out


@router.get("/admin/overview")
async def overview(_: AdminUser, s: Session, ctx: CtxDep) -> dict:
    users = (await s.execute(select(User).order_by(User.created_ms))).scalars().all()
    chars = (await s.execute(select(Character).where(Character.archived.is_(False)).order_by(Character.id))).scalars().all()
    posts = dict((await s.execute(select(Draft.character_id, func.count()).where(
        Draft.status.in_(("published", "partially_published"))).group_by(Draft.character_id))).all())
    out_users = []
    for u in users:
        out_users.append({"id": u.id, "name": f"@{u.username}" if u.username else (u.first_name or str(u.id)),
                          "is_active": u.is_active, "budget_usd": u.budget_usd,
                          "spent_usd": round(await budget.spent(s, u.id, ctx.settings), 2),
                          "spent_own_usd": round(await budget.spent(s, u.id, ctx.settings, "own"), 2),
                          "characters": sum(1 for c in chars if c.user_id == u.id)})
    return {
        "users": out_users,
        "characters": [{"id": c.id, "user_id": c.user_id, "name": c.name, "handle": c.handle, "status": c.status,
                        "autopilot": c.autopilot, "approved_streak": c.approved_streak,
                        "posts": posts.get(c.id, 0)} for c in chars],
        "total_spent_usd": round(sum(x["spent_usd"] for x in out_users), 2),
    }


class AutopilotIn(BaseModel):
    autopilot: bool


@router.patch("/admin/characters/{cid}")
async def admin_autopilot(cid: int, body: AutopilotIn, _: AdminUser, s: Session, ctx: CtxDep) -> dict:
    ch = await s.get(Character, cid)
    if ch is None:
        raise HTTPException(404, "not_found")
    await autopilot.set_autopilot(ctx, s, ch, body.autopilot, by_owner=True)
    await s.commit()
    return {"id": ch.id, "autopilot": ch.autopilot}
