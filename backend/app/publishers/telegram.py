"""Publishing to a Telegram channel with the bot (the bot must be an admin with "post messages")."""

from __future__ import annotations

from .base import Creds, Post, Published, PublishError

CAPTION_LIMIT = 1024


class TelegramChannelPublisher:
    platform = "telegram"
    needs_public_urls = False

    def __init__(self, bot) -> None:
        self.bot = bot

    def _chat(self, c: Creds):
        return int(c.external_id) if c.external_id.lstrip("-").isdigit() else c.external_id

    async def publish(self, c: Creds, post: Post, state: dict) -> Published:
        if state.get("message_ids"):
            return Published(str(state["message_ids"][0]), state.get("permalink"))
        if self.bot is None:
            raise PublishError("bot_not_running", "the bot token is not configured")
        from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
        from aiogram.types import BufferedInputFile, InputMediaPhoto

        files = [BufferedInputFile(m.data or b"", filename=f"{i + 1}.jpg") for i, m in enumerate(post.media[:10])]
        long = len(post.caption) > CAPTION_LIMIT
        chat = self._chat(c)
        try:
            if len(files) == 1:
                msgs = [await self.bot.send_photo(chat, files[0], caption=None if long else post.caption,
                                                  parse_mode=None)]
            else:
                media = [InputMediaPhoto(media=f, caption=post.caption if (i == 0 and not long) else None,
                                         parse_mode=None) for i, f in enumerate(files)]
                msgs = await self.bot.send_media_group(chat, media)
            ids = [m.message_id for m in msgs]
            if long:
                ids.append((await self.bot.send_message(chat, post.caption, parse_mode=None)).message_id)
        except TelegramRetryAfter as e:
            raise PublishError("rate_limited", str(e), retryable=True, retry_after_ms=e.retry_after * 1000) from e
        except TelegramForbiddenError as e:
            raise PublishError("bot_not_admin", str(e), account_broken=True) from e
        except TelegramBadRequest as e:
            if "not enough rights" in str(e).lower() or "chat not found" in str(e).lower():
                raise PublishError("bot_not_admin", str(e), account_broken=True) from e
            raise PublishError("platform_error", str(e)) from e
        state["message_ids"] = ids
        username = c.username.lstrip("@")
        state["permalink"] = f"https://t.me/{username}/{ids[0]}" if username else None
        return Published(str(ids[0]), state["permalink"])

    async def delete(self, c: Creds, external_id: str, state: dict) -> None:
        ids = state.get("message_ids") or [int(external_id)]
        await self.bot.delete_messages(self._chat(c), ids)

    async def metrics(self, c: Creds, external_id: str) -> dict:
        return {}  # the Bot API has no post statistics

    async def account_stats(self, c: Creds) -> dict:
        if self.bot is None:
            return {}
        return {"followers": await self.bot.get_chat_member_count(self._chat(c))}
