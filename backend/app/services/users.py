from __future__ import annotations

import secrets
import time

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..models import InviteCode, InviteRedemption, User
from ..telegram_auth import TgUser


def now_ms() -> int:
    return int(time.time() * 1000)


class InviteError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


async def get_or_create(s: AsyncSession, tg: TgUser, settings: Settings) -> User:
    u = await s.get(User, tg.id)
    now = now_ms()
    if u is None:
        u = User(id=tg.id, first_name=tg.first_name, username=tg.username, language=tg.language,
                 budget_usd=settings.default_budget_usd, created_ms=now, is_active=False)
        s.add(u)
    else:
        u.first_name, u.username = tg.first_name or u.first_name, tg.username or u.username
    if tg.id == settings.owner_id:
        u.is_active = True
    u.last_seen_ms = now
    await s.flush()
    return u


def new_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I
    return "".join(secrets.choice(alphabet) for _ in range(8))


async def create_invite(s: AsyncSession, created_by: int, max_uses: int, note: str = "",
                        code: str | None = None) -> InviteCode:
    inv = InviteCode(code=(code or new_code()).upper(), max_uses=max(1, max_uses), note=note[:200],
                     created_by=created_by, created_ms=now_ms())
    s.add(inv)
    await s.flush()
    return inv


async def redeem(s: AsyncSession, user: User, code: str) -> User:
    """Activate a user by invite code. The usage counter is bumped atomically, so a code with
    max_uses=1 can't be redeemed twice by parallel requests."""
    if user.is_active:
        return user
    code = code.strip().upper()
    inv = await s.get(InviteCode, code)
    if inv is None or not inv.active:
        raise InviteError("invite_not_found")
    res = await s.execute(
        update(InviteCode).where(InviteCode.code == code, InviteCode.active.is_(True),
                                 InviteCode.uses < InviteCode.max_uses)
        .values(uses=InviteCode.uses + 1)
    )
    if res.rowcount != 1:
        raise InviteError("invite_exhausted")
    s.add(InviteRedemption(code=code, user_id=user.id, created_ms=now_ms()))
    user.is_active = True
    user.invite_code = code
    await s.flush()
    return user


async def list_invites(s: AsyncSession) -> list[InviteCode]:
    return list((await s.execute(select(InviteCode).order_by(InviteCode.created_ms.desc()))).scalars())
