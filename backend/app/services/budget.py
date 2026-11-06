"""Spending: every paid operation writes a Usage row; the monthly shared budget stops generation."""

from __future__ import annotations

import contextlib
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..models import Usage, User
from ..providers.base import Usage as UsageItem
from .users import now_ms

log = logging.getLogger("purrpost.budget")


class BudgetExceeded(Exception):
    def __init__(self, spent: float, limit: float) -> None:
        super().__init__(f"budget exhausted: ${spent:.2f} of ${limit:.2f}")
        self.spent, self.limit = spent, limit


def month_key(settings: Settings, ms: int | None = None) -> str:
    dt = datetime.fromtimestamp((ms or now_ms()) / 1000, ZoneInfo(settings.timezone))
    return dt.strftime("%Y-%m")


def month_start_ms(settings: Settings, ms: int | None = None) -> int:
    dt = datetime.fromtimestamp((ms or now_ms()) / 1000, ZoneInfo(settings.timezone))
    return int(dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)


async def spent(s: AsyncSession, user_id: int, settings: Settings, billed_to: str = "shared",
                now: int | None = None) -> float:
    q = select(func.coalesce(func.sum(Usage.cost_usd), 0.0)).where(
        Usage.user_id == user_id, Usage.billed_to == billed_to, Usage.created_ms >= month_start_ms(settings, now))
    return float((await s.execute(q)).scalar_one())


def record(s: AsyncSession, user_id: int, u: UsageItem, character_id: int | None = None) -> Usage:
    row = Usage(user_id=user_id, character_id=character_id, provider=u.provider, kind=u.kind, units=u.units,
                cost_usd=u.cost_usd, billed_to=u.billed_to, created_ms=now_ms())
    s.add(row)
    return row


async def ensure(s: AsyncSession, ctx, user: User, providers) -> None:
    """Raise BudgetExceeded if this user's shared budget is spent (own keys don't count). The bot tells the
    user once a month."""
    if not providers.any_shared:
        return
    used = await spent(s, user.id, ctx.settings)
    if used < user.budget_usd:
        return
    month = month_key(ctx.settings)
    if user.budget_notified_month != month:
        user.budget_notified_month = month
        await s.commit()
        if ctx.notifier:
            with contextlib.suppress(Exception):
                await ctx.notifier.send(
                    user.id,
                    f"Бюджет на этот месяц закончился: потрачено ${used:.2f} из ${user.budget_usd:.2f}. "
                    "Генерация остановлена до 1-го числа. Можно попросить владельца поднять лимит "
                    "или добавить свои ключи fal.ai и Anthropic в профиле.")
    raise BudgetExceeded(used, user.budget_usd)


async def summary(s: AsyncSession, user: User, settings: Settings) -> dict:
    shared = await spent(s, user.id, settings)
    own = await spent(s, user.id, settings, "own")
    rows = (await s.execute(
        select(Usage.character_id, func.sum(Usage.cost_usd)).where(
            Usage.user_id == user.id, Usage.created_ms >= month_start_ms(settings)).group_by(Usage.character_id)
    )).all()
    return {"limit": user.budget_usd, "spent": round(shared, 2), "spent_own_keys": round(own, 2),
            "remaining": round(max(0.0, user.budget_usd - shared), 2), "exhausted": shared >= user.budget_usd,
            "month": month_key(settings), "by_character": {str(c or 0): round(v, 2) for c, v in rows}}
