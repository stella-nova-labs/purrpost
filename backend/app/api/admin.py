from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..models import InviteCode, User
from ..services import budget
from ..services.users import create_invite, list_invites
from .deps import AdminUser, Session, SettingsDep

router = APIRouter(prefix="/api/admin")


def invite_out(i: InviteCode, bot_username: str | None) -> dict:
    link = f"https://t.me/{bot_username}?start=inv_{i.code}" if bot_username else None
    return {"code": i.code, "max_uses": i.max_uses, "uses": i.uses, "note": i.note, "active": i.active,
            "created_ms": i.created_ms, "link": link}


class InviteIn(BaseModel):
    max_uses: int = Field(1, ge=1, le=1000)
    note: str = ""


@router.get("/invites")
async def invites(_: AdminUser, s: Session, request: Request) -> list[dict]:
    return [invite_out(i, request.app.state.bot_username) for i in await list_invites(s)]


@router.post("/invites")
async def new_invite(body: InviteIn, a: AdminUser, s: Session, request: Request) -> dict:
    inv = await create_invite(s, a.id, body.max_uses, body.note)
    await s.commit()
    return invite_out(inv, request.app.state.bot_username)


@router.delete("/invites/{code}")
async def disable_invite(code: str, _: AdminUser, s: Session) -> dict:
    inv = await s.get(InviteCode, code.upper())
    if inv is None:
        raise HTTPException(404, "not_found")
    inv.active = False
    await s.commit()
    return {"ok": True}


class UserPatch(BaseModel):
    budget_usd: float | None = Field(None, ge=0, le=10000)
    is_active: bool | None = None


@router.get("/users")
async def users(_: AdminUser, s: Session, settings: SettingsDep) -> list[dict]:
    rows = (await s.execute(select(User).order_by(User.created_ms))).scalars().all()
    return [{"id": u.id, "first_name": u.first_name, "username": u.username, "is_active": u.is_active,
             "budget_usd": u.budget_usd, "invite_code": u.invite_code, "created_ms": u.created_ms,
             "spent_usd": round(await budget.spent(s, u.id, settings), 2),
             "spent_own_usd": round(await budget.spent(s, u.id, settings, "own"), 2),
             "own_keys": bool(u.fal_key_enc or u.anthropic_key_enc)} for u in rows]


@router.patch("/users/{uid}")
async def patch_user(uid: int, body: UserPatch, _: AdminUser, s: Session, settings: SettingsDep) -> dict:
    u = await s.get(User, uid)
    if u is None:
        raise HTTPException(404, "not_found")
    if body.budget_usd is not None:
        u.budget_usd = body.budget_usd
    if body.is_active is not None and uid != settings.owner_id:
        u.is_active = body.is_active
    await s.commit()
    return {"ok": True}
