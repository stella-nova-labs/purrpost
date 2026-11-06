from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services.users import InviteError, redeem
from .deps import AnyUser, Session, SettingsDep

router = APIRouter(prefix="/api")


def user_out(u, settings) -> dict:
    return {"id": u.id, "first_name": u.first_name, "username": u.username, "is_active": u.is_active,
            "is_owner": u.id == settings.owner_id, "is_admin": u.id in settings.admin_id_set}


@router.get("/me")
async def me(u: AnyUser, settings: SettingsDep) -> dict:
    return {"user": user_out(u, settings), "fake_providers": settings.dev_fake_providers}


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
