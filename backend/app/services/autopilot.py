"""Autopilot: after N approved posts in a row (AUTOPILOT_STREAK, default 10) drafts that pass QA are scheduled
without review. The owner can switch it on manually for anyone; users can always switch it off."""

from __future__ import annotations

import html

from .notify import Button


def unlocked(ctx, ch) -> bool:
    return ch.autopilot or ch.approved_streak >= ctx.settings.autopilot_streak


async def after_approval(ctx, s, ch) -> None:
    if ch.autopilot or ch.approved_streak < ctx.settings.autopilot_streak:
        return
    ch.autopilot = True
    await s.flush()
    buttons = [[Button("Открыть Purrpost", web_app=ctx.settings.webapp_url)]] if ctx.settings.webapp_url else None
    await ctx.notifier.send(
        ch.user_id,
        f"🤖 <b>{html.escape(ch.name)}</b>: {ch.approved_streak} одобренных постов подряд — включаю автопилот. "
        "Черновики, прошедшие проверку качества, будут выходить сами, а я пришлю каждый опубликованный пост "
        "с кнопкой «Удалить». Выключить автопилот можно на странице персонажа.", buttons)


async def set_autopilot(ctx, s, ch, on: bool, by_owner: bool) -> None:
    if on and not by_owner and not unlocked(ctx, ch):
        from .approval import ActionError
        raise ActionError("autopilot_locked")
    ch.autopilot = on
    if not on and not by_owner:
        ch.approved_streak = min(ch.approved_streak, ctx.settings.autopilot_streak)
    await s.flush()
