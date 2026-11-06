"""Which bot message shows which draft: users reply to a draft message to change its caption."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import BotMessage


async def remember_message(s: AsyncSession, chat_id: int, message_id: int, draft_id: int) -> None:
    s.add(BotMessage(chat_id=chat_id, message_id=message_id, draft_id=draft_id))
    await s.flush()


async def draft_for_message(s: AsyncSession, chat_id: int, message_id: int) -> int | None:
    return (await s.execute(select(BotMessage.draft_id).where(BotMessage.chat_id == chat_id,
                                                              BotMessage.message_id == message_id))
            ).scalar_one_or_none()
