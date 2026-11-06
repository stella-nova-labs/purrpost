from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services import budget
from ..services.users import InviteError, redeem
from .deps import AnyUser, Session, SettingsDep

router = APIRouter(prefix="/api")


def user_out(u, settings) -> dict:
    return {"id": u.id, "first_name": u.first_name, "username": u.username, "is_active": u.is_active,
            "is_owner": u.id == settings.owner_id, "is_admin": u.id in settings.admin_id_set}


@router.get("/me")
async def me(u: AnyUser, s: Session, settings: SettingsDep) -> dict:
    out = {"user": user_out(u, settings), "fake_providers": settings.dev_fake_providers,
           # without a Meta app, Instagram/Threads can't be connected: posts are handed over by the bot instead
           "platforms": {"instagram": bool(settings.meta_app_id) or settings.dev_fake_providers,
                         "threads": bool(settings.threads_app_id) or settings.dev_fake_providers}}
    if u.is_active:
        out["budget"] = await budget.summary(s, u, settings)
        out["own_keys"] = {"fal": bool(u.fal_key_enc), "anthropic": bool(u.anthropic_key_enc)}
    return out


class RedeemIn(BaseModel):
    code: str


@router.post("/invite/redeem")
async def redeem_code(body: RedeemIn, u: AnyUser, s: Session, settings: SettingsDep) -> dict:
    try:
        await redeem(s, u, body.code)
    except InviteError as e:
        raise HTTPException(400, e.code) from e
    await s.commit()
    return {"user": user_out(u, settings)}
