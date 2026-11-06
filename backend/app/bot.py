"""Telegram bot: /start (with an invite code), the Mini App button, and draft approval buttons."""

from __future__ import annotations

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonWebApp, Message, WebAppInfo

from .config import Settings
from .context import Ctx
from .services.users import InviteError, get_or_create, redeem
from .telegram_auth import TgUser, parse_invite

router = Router()

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


@router.message(CommandStart())
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


def create_bot(settings: Settings) -> Bot:
    return Bot(settings.bot_token, default=DefaultBotProperties(parse_mode="HTML"))


def create_dispatcher(ctx: Ctx) -> Dispatcher:
    dp = Dispatcher()
    dp["ctx"] = ctx
    dp.include_router(router)
    return dp


async def setup_menu(bot: Bot, settings: Settings) -> None:
    if settings.webapp_url:
        await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="Purrpost",
                                                                    web_app=WebAppInfo(url=settings.webapp_url)))
