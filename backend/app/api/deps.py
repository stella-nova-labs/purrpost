from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..models import User
from ..services.users import InviteError, get_or_create, redeem
from ..telegram_auth import AuthError, TgUser, parse_invite, validate_init_data


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.db.sessions() as s:
        yield s


def get_tg_user(
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> TgUser:
    """`Authorization: tma <initData>`; locally with DEV_AUTH=1: `tma dev:<id>[:start_param]`."""
    if not authorization or not authorization.startswith("tma "):
        raise HTTPException(401, "auth_required")
    raw = authorization[4:]
    if settings.dev_auth and raw.startswith("dev:"):
        parts = raw.split(":")
        if len(parts) < 2 or not parts[1].isdigit():
            raise HTTPException(401, "bad_dev_auth")
        return TgUser(id=int(parts[1]), first_name=f"dev{parts[1]}", username=f"dev{parts[1]}",
                      start_param=parts[2] if len(parts) > 2 else None)
    try:
        return validate_init_data(raw, settings.bot_token, settings.init_data_max_age)
    except AuthError as e:
        raise HTTPException(401, str(e)) from e


Session = Annotated[AsyncSession, Depends(get_session)]
CurrentTg = Annotated[TgUser, Depends(get_tg_user)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


async def get_user(s: Session, tg: CurrentTg, settings: SettingsDep) -> User:
    """The signed-in user (may be inactive: no invite yet). A start parameter `inv_<CODE>` redeems the code."""
    u = await get_or_create(s, tg, settings)
    code = parse_invite(tg.start_param)
    if code and not u.is_active:
        with contextlib.suppress(InviteError):
            await redeem(s, u, code)
    await s.commit()
    return u


AnyUser = Annotated[User, Depends(get_user)]


def get_active_user(u: AnyUser) -> User:
    if not u.is_active:
        raise HTTPException(403, "invite_required")
    return u


ActiveUser = Annotated[User, Depends(get_active_user)]


def get_admin(u: ActiveUser, settings: SettingsDep) -> User:
    if u.id not in settings.admin_id_set:
        raise HTTPException(403, "admin_only")
    return u


AdminUser = Annotated[User, Depends(get_admin)]
