"""Connecting social accounts to a character: Instagram and Threads by OAuth, a Telegram channel by name."""

from __future__ import annotations

import html

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..models import Account, Character
from ..services import oauth
from ..services.crypto import encrypt
from ..services.users import now_ms
from .characters import load_character
from .deps import ActiveUser, CtxDep, Session

router = APIRouter(prefix="/api")

TESTER_HINT = (
    "Пока приложение Meta в режиме разработки, ваш Instagram должен быть добавлен в него тестером. "
    "Попросите владельца Purrpost добавить ваш ник в Meta for Developers (App roles → Roles → Instagram Testers), "
    "затем примите приглашение в Instagram: Настройки → Приложения и сайты → Приглашения тестировщика. "
    "Аккаунт должен быть профессиональным (Business или Creator)."
)
ERRORS = {
    "not_tester": TESTER_HINT,
    "not_business": "Нужен профессиональный аккаунт Instagram (Business или Creator). Переключите тип аккаунта в "
                    "настройках Instagram и подключите ещё раз.",
    "state_expired": "Ссылка для входа устарела. Начните подключение заново из приложения.",
    "bad_state": "Ссылка для входа повреждена. Начните подключение заново из приложения.",
    "access_denied": "Вы отменили вход.",
}


def account_out(a: Account) -> dict:
    return {"id": a.id, "platform": a.platform, "username": a.username, "status": a.status,
            "last_error": a.last_error, "token_expires_ms": a.token_expires_ms, "title": (a.meta or {}).get("title")}


@router.get("/characters/{cid}/accounts")
async def list_accounts(cid: int, u: ActiveUser, s: Session) -> list[dict]:
    await load_character(s, u, cid)
    rows = (await s.execute(select(Account).where(Account.character_id == cid).order_by(Account.id))).scalars()
    return [account_out(a) for a in rows]


@router.get("/oauth/{platform}/start")
async def oauth_start(platform: str, character_id: int, u: ActiveUser, s: Session, ctx: CtxDep) -> dict:
    await load_character(s, u, character_id)
    if platform not in ("instagram", "threads"):
        raise HTTPException(404, "not_found")
    try:
        url = oauth.authorize_url(ctx.settings, platform, oauth.sign_state(ctx.settings, u.id, character_id, platform))
    except oauth.OAuthError as e:
        raise HTTPException(400, e.code) from e
    return {"url": url}


def _page(title: str, text: str, ok: bool, settings) -> HTMLResponse:
    back = f'<a class="btn" href="{html.escape(settings.webapp_url)}">Вернуться в Purrpost</a>' \
        if settings.webapp_url.startswith("https://t.me/") else ""
    color = "#7FD8A6" if ok else "#FF8A3D"
    return HTMLResponse(f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Purrpost</title>
<style>body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#120F16;
color:#F6F1F8;font:16px/1.5 system-ui,sans-serif;padding:24px;box-sizing:border-box}}
.c{{max-width:420px}}h1{{font-size:22px;color:{color}}}p{{color:#C9BFD3}}
.btn{{display:inline-block;margin-top:12px;padding:12px 18px;border-radius:12px;background:#FF8A3D;color:#120F16;
font-weight:700;text-decoration:none}}</style></head>
<body><div class="c"><h1>{html.escape(title)}</h1><p>{html.escape(text)}</p>{back}
<p>Это окно можно закрыть и вернуться в Telegram.</p></div></body></html>""", status_code=200 if ok else 400)


@router.get("/oauth/{platform}/callback", include_in_schema=False)
async def oauth_callback(platform: str, s: Session, ctx: CtxDep, state: str = "", code: str = "",
                         error: str = "", error_description: str = "") -> HTMLResponse:
    st = ctx.settings
    name = {"instagram": "Instagram", "threads": "Threads"}.get(platform, platform)
    try:
        if error:
            raise oauth.OAuthError("access_denied" if error == "access_denied" else "oauth_failed",
                                   error_description or error)
        uid, cid, pl = oauth.read_state(st, state)
        if pl != platform:
            raise oauth.OAuthError("bad_state")
        ch = await s.get(Character, cid)
        if ch is None or ch.user_id != uid:
            raise oauth.OAuthError("bad_state")
        tok = await oauth.exchange(st, ctx.http, platform, code, now_ms())
    except oauth.OAuthError as e:
        text = ERRORS.get(e.code) or f"Instagram ответил: {e.message}. " + (TESTER_HINT if platform == "instagram" else "")
        return _page(f"{name} не подключён", text, False, st)
    a = (await s.execute(select(Account).where(Account.character_id == cid, Account.platform == platform))
         ).scalar_one_or_none()
    if a is None:
        a = Account(user_id=uid, character_id=cid, platform=platform, created_ms=now_ms())
        s.add(a)
    a.external_id, a.username = tok.user_id, tok.username
    a.token_enc, a.token_expires_ms, a.token_refreshed_ms = encrypt(st, tok.access_token), tok.expires_ms, now_ms()
    a.status, a.last_error, a.meta = "ok", None, {"account_type": tok.account_type}
    await s.commit()
    await ctx.notifier.send(uid, f"{name} @{html.escape(tok.username)} подключён к <b>{html.escape(ch.name)}</b>.")
    return _page(f"{name} подключён", f"@{tok.username} теперь публикует посты {ch.name}.", True, st)


class TelegramIn(BaseModel):
    channel: str = Field(min_length=2, max_length=64)


@router.post("/characters/{cid}/accounts/telegram")
async def connect_telegram(cid: int, body: TelegramIn, u: ActiveUser, s: Session, ctx: CtxDep) -> dict:
    ch = await load_character(s, u, cid)
    raw = body.channel.strip()
    raw = raw.replace("https://t.me/", "@") if raw.startswith("https://t.me/") else raw
    chat: int | str = int(raw) if raw.lstrip("-").isdigit() else ("@" + raw.lstrip("@"))
    title, username = str(chat), raw.lstrip("@") if isinstance(chat, str) else ""
    if not ctx.settings.dev_fake_providers:
        if ctx.bot is None:
            raise HTTPException(400, "bot_not_running")
        try:
            info = await ctx.bot.get_chat(chat)
            me = await ctx.bot.get_me()
            member = await ctx.bot.get_chat_member(info.id, me.id)
        except Exception as e:  # noqa: BLE001 - aiogram raises several kinds here
            raise HTTPException(400, "channel_not_found") from e
        if member.status != "administrator" or not getattr(member, "can_post_messages", False):
            raise HTTPException(400, "bot_not_admin")
        chat, title, username = info.id, info.title or str(chat), info.username or ""
    a = (await s.execute(select(Account).where(Account.character_id == cid, Account.platform == "telegram"))
         ).scalar_one_or_none()
    if a is None:
        a = Account(user_id=u.id, character_id=ch.id, platform="telegram", created_ms=now_ms())
        s.add(a)
    a.external_id, a.username, a.status, a.last_error, a.meta = str(chat), username, "ok", None, {"title": title}
    await s.commit()
    return account_out(a)


@router.delete("/accounts/{aid}")
async def disconnect(aid: int, u: ActiveUser, s: Session) -> dict:
    a = await s.get(Account, aid)
    if a is None or a.user_id != u.id:
        raise HTTPException(404, "not_found")
    await s.delete(a)
    await s.commit()
    return {"ok": True}
