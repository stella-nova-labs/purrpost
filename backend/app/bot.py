"""Telegram bot: /start (with an invite code), the Mini App button, and draft approval buttons."""

from __future__ import annotations

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonWebApp, Message,
                           WebAppInfo)

from .config import Settings
from .context import Ctx
from .services import approval
from .services.users import InviteError, get_or_create, redeem
from .telegram_auth import TgUser, parse_invite

WELCOME = (
    "<b>Purrpost</b> ведёт Instagram ИИ-котов: придумывает посты в их характере, рисует карусели "
    "и публикует по расписанию. Вы только одобряете черновики.\n\nОткройте приложение кнопкой ниже."
)
NEED_INVITE = (
    "Purrpost пока работает по приглашениям. Попросите у владельца инвайт-код и введите его в приложении "
    "или откройте ссылку-приглашение."
)


def app_button(settings: Settings, text: str = "Открыть Purrpost") -> InlineKeyboardMarkup | None:
    if not settings.webapp_url:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=text, web_app=WebAppInfo(url=settings.webapp_url))]])


async def start(message: Message, command: CommandObject, ctx: Ctx) -> None:
    fu = message.from_user
    if fu is None or fu.is_bot:
        return
    tg = TgUser(id=fu.id, first_name=fu.first_name or "", username=fu.username, language=fu.language_code)
    async with ctx.db.sessions() as s:
        u = await get_or_create(s, tg, ctx.settings)
        code = parse_invite(command.args)
        note = ""
        if code and not u.is_active:
            try:
                await redeem(s, u, code)
                note = "Инвайт принят, добро пожаловать!\n\n"
            except InviteError:
                note = "Этот инвайт-код не подошёл: он неверный или уже израсходован.\n\n"
        await s.commit()
        active = u.is_active
    await message.answer(note + (WELCOME if active else NEED_INVITE), reply_markup=app_button(ctx.settings))


async def draft_button(q: CallbackQuery, ctx: Ctx) -> None:
    text = await approval.handle_callback(ctx, q.from_user.id, q.data or "")
    await q.answer(text[:190])
    if q.message and isinstance(q.message, Message) and q.message.text is not None:
        done = text.startswith(("✅", "🗑", "🔄", "🖼"))
        if done:
            # the action is taken: drop the buttons and note what happened under the draft
            await q.message.edit_text(q.message.html_text + f"\n\n<i>{approval.escape(text)}</i>", reply_markup=None)


async def published_button(q: CallbackQuery, ctx: Ctx) -> None:
    from .services import publishing
    text = await publishing.handle_callback(ctx, q.from_user.id, q.data or "")
    await q.answer(text[:190], show_alert=True)
    if q.message and isinstance(q.message, Message) and q.message.text is not None and text.startswith("🗑"):
        await q.message.edit_text(q.message.html_text + f"\n\n<i>{approval.escape(text)}</i>", reply_markup=None)


async def caption_reply(message: Message, ctx: Ctx) -> None:
    res = await approval.handle_reply(ctx, message.from_user.id, message.reply_to_message.message_id, message.text)
    if res is not None and res != "ok":
        await message.answer(res)


def create_bot(settings: Settings) -> Bot:
    return Bot(settings.bot_token, default=DefaultBotProperties(parse_mode="HTML"))


def build_router() -> Router:
    """A fresh router per dispatcher (aiogram routers can be attached only once)."""
    r = Router()
    r.message.register(start, CommandStart())
    r.callback_query.register(draft_button, F.data.startswith("d:"))
    r.callback_query.register(published_button, F.data.startswith("p:"))
    r.message.register(caption_reply, F.reply_to_message, F.text)
    return r


def create_dispatcher(ctx: Ctx) -> Dispatcher:
    dp = Dispatcher()
    dp["ctx"] = ctx
    dp.include_router(build_router())
    return dp


async def setup_menu(bot: Bot, settings: Settings) -> None:
    if settings.webapp_url:
        await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="Purrpost",
                                                                    web_app=WebAppInfo(url=settings.webapp_url)))
