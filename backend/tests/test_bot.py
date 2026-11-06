"""The aiogram wiring: real Dispatcher and handlers, a fake Bot API session that records calls."""

import datetime

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage
from aiogram.types import Chat, Message, Update

from app.bot import create_dispatcher

from .conftest import OWNER, auth, invite_user
from .test_pipeline import generate


class RecordingSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, AnswerCallbackQuery):
            return True
        if isinstance(method, (SendMessage, EditMessageText)):
            return Message(message_id=500 + len(self.calls), date=datetime.datetime.now(),
                           chat=Chat(id=getattr(method, "chat_id", 1) or 1, type="private"), text=method.text)
        return True

    async def close(self):
        pass

    async def stream_content(self, *a, **kw):  # pragma: no cover
        yield b""


def user(uid):
    return {"id": uid, "is_bot": False, "first_name": "U"}


def msg(uid, mid, text, **extra):
    return {"message_id": mid, "date": 1700000000, "chat": {"id": uid, "type": "private"}, "from": user(uid),
            "text": text, **extra}


async def feed(ctx, update: dict):
    session = RecordingSession()
    bot = Bot("123456:TEST-TOKEN", session=session)
    dp = create_dispatcher(ctx)
    await dp.feed_update(bot, Update.model_validate(update, context={"bot": bot}))
    return session.calls


async def test_start_with_invite_link(client, ctx):
    code = (await client.post("/api/admin/invites", json={}, headers=auth(OWNER))).json()["code"]
    calls = await feed(ctx, {"update_id": 1, "message": msg(80, 1, f"/start inv_{code}")})
    assert "Инвайт принят" in calls[0].text
    assert (await client.get("/api/me", headers=auth(80))).json()["user"]["is_active"]
    calls = await feed(ctx, {"update_id": 2, "message": msg(81, 1, "/start")})
    assert "по приглашениям" in calls[0].text


async def test_approve_button_through_dispatcher(client, ctx):
    _, d = await generate(client, ctx)
    m = ctx.notifier.last(OWNER)
    calls = await feed(ctx, {"update_id": 3, "callback_query": {
        "id": "cb1", "from": user(OWNER), "chat_instance": "x", "data": f"d:ok:{d['id']}",
        "message": msg(OWNER, m.message_id, "<b>Don</b> draft")}})
    answer = next(c for c in calls if isinstance(c, AnswerCallbackQuery))
    edit = next(c for c in calls if isinstance(c, EditMessageText))
    assert answer.text.startswith("✅") and edit.reply_markup is None and "Запланировано" in edit.text
    assert (await client.get(f"/api/drafts/{d['id']}", headers=auth(OWNER))).json()["status"] == "scheduled"


async def test_caption_reply_through_dispatcher(client, ctx):
    await invite_user(client, 82)
    _, d = await generate(client, ctx)
    m = ctx.notifier.last(OWNER)
    await feed(ctx, {"update_id": 4, "message": msg(OWNER, 900, "From the bot", reply_to_message=msg(OWNER, m.message_id, "x"))})
    assert (await client.get(f"/api/drafts/{d['id']}", headers=auth(OWNER))).json()["caption"] == "From the bot"
    # an unrelated reply produces no answer
    calls = await feed(ctx, {"update_id": 5, "message": msg(82, 901, "hello", reply_to_message=msg(82, 7, "x"))})
    assert calls == []
