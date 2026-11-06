"""Messages from the bot to users. The pipeline never talks to aiogram directly: it calls a Notifier.

`MemoryNotifier` keeps messages in memory (tests and local runs without a bot token)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

log = logging.getLogger("purrpost.notify")


@dataclass
class Button:
    text: str
    data: str | None = None  # callback data
    url: str | None = None
    web_app: str | None = None


@dataclass
class Sent:
    chat_id: int
    text: str
    photos: list[str] = field(default_factory=list)
    buttons: list[list[Button]] = field(default_factory=list)
    message_id: int = 0


class Notifier(Protocol):
    async def send(self, chat_id: int, text: str, buttons: list[list[Button]] | None = None) -> int: ...

    async def send_album(self, chat_id: int, photo_urls: list[str], text: str,
                         buttons: list[list[Button]] | None = None) -> int: ...


class MemoryNotifier:
    def __init__(self) -> None:
        self.sent: list[Sent] = []
        self._next = 1000

    async def send(self, chat_id: int, text: str, buttons: list[list[Button]] | None = None) -> int:
        self._next += 1
        self.sent.append(Sent(chat_id, text, [], buttons or [], self._next))
        log.info("bot -> %s: %s", chat_id, text.splitlines()[0] if text else "")
        return self._next

    async def send_album(self, chat_id: int, photo_urls: list[str], text: str,
                         buttons: list[list[Button]] | None = None) -> int:
        self._next += 1
        self.sent.append(Sent(chat_id, text, list(photo_urls), buttons or [], self._next))
        log.info("bot album -> %s (%d photos)", chat_id, len(photo_urls))
        return self._next

    def last(self, chat_id: int | None = None) -> Sent | None:
        for m in reversed(self.sent):
            if chat_id is None or m.chat_id == chat_id:
                return m
        return None


def _markup(buttons: list[list[Button]] | None) -> Any:
    if not buttons:
        return None
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
    rows = []
    for row in buttons:
        rows.append([InlineKeyboardButton(text=b.text, callback_data=b.data, url=b.url,
                                          web_app=WebAppInfo(url=b.web_app) if b.web_app else None) for b in row])
    return InlineKeyboardMarkup(inline_keyboard=rows)


class BotNotifier:
    def __init__(self, bot: Any) -> None:
        self.bot = bot

    async def send(self, chat_id: int, text: str, buttons: list[list[Button]] | None = None) -> int:
        m = await self.bot.send_message(chat_id, text, reply_markup=_markup(buttons))
        return m.message_id

    async def send_album(self, chat_id: int, photo_urls: list[str], text: str,
                         buttons: list[list[Button]] | None = None) -> int:
        """Media groups can't carry buttons: the album goes first, then the caption with buttons.
        Returns the id of the caption message (users reply to it to edit the caption)."""
        from aiogram.types import InputMediaPhoto
        if photo_urls:
            if len(photo_urls) == 1:
                await self.bot.send_photo(chat_id, photo_urls[0])
            else:
                await self.bot.send_media_group(chat_id, [InputMediaPhoto(media=u) for u in photo_urls[:10]])
        m = await self.bot.send_message(chat_id, text, reply_markup=_markup(buttons))
        return m.message_id
