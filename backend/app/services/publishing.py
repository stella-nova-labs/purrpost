"""Publishing: scheduled drafts -> one Publication per connected platform -> retries -> metrics later."""

from __future__ import annotations

import contextlib
import html
import logging

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Account, Character, Draft, Publication
from ..publishers.base import Creds, Media, Post, PublishError
from .crypto import decrypt
from .notify import Button
from .pipeline import final_caption, remember
from .users import now_ms

log = logging.getLogger("purrpost.publishing")

MAX_ATTEMPTS = 5
BASE_DELAY_MS = 60_000
STUCK_MS = 15 * 60_000
REFRESH_BEFORE_MS = 10 * 86_400_000
PLATFORM_NAMES = {"instagram": "Instagram", "threads": "Threads", "telegram": "Telegram-канал"}

ERROR_TEXTS = {
    "token_expired": "токен истёк — переподключите {platform} в приложении",
    "permission_denied": "нет прав на публикацию — переподключите {platform}",
    "publish_limit": "достигнут лимит публикаций за 24 ч, попробую позже",
    "rate_limited": "слишком много запросов, попробую позже",
    "media_fetch_failed": "{platform} не смог скачать картинки",
    "media_rejected": "{platform} не принял картинки",
    "platform_unavailable": "{platform} не отвечает",
    "bot_not_admin": "бот не админ канала или не может публиковать",
    "bot_not_running": "бот не запущен",
    "no_accounts": "у персонажа нет подключённых соцсетей",
    "delete_not_supported": "{platform} не даёт удалить пост через API — удалите его вручную",
}


def error_text(code: str | None, platform: str = "") -> str:
    return ERROR_TEXTS.get(code or "", code or "ошибка").format(platform=PLATFORM_NAMES.get(platform, platform))


def backoff(attempts: int) -> int:
    """1, 2, 4, 8 minutes..."""
    return BASE_DELAY_MS * 2 ** max(0, attempts - 1)


def creds(ctx, a: Account) -> Creds:
    return Creds(a.external_id, decrypt(ctx.settings, a.token_enc), a.username, a.meta or {})


def external_url(ctx, key: str) -> str:
    u = ctx.storage.url(key, ctx.settings.presign_ttl_sec)
    return ctx.settings.base_url + u if u.startswith("/") else u


async def accounts_for(s: AsyncSession, character_id: int) -> list[Account]:
    return list((await s.execute(select(Account).where(Account.character_id == character_id)
                                 .order_by(Account.id))).scalars())


# ---------- step 1: due drafts -> publications ----------

async def start_due(ctx, now: int | None = None) -> int:
    """Scheduled drafts whose time has come get a Publication per connected platform (idempotent)."""
    now = now or now_ms()
    n = 0
    async with ctx.db.sessions() as s:
        due = (await s.execute(select(Draft).where(Draft.status == "scheduled", Draft.slot_ms <= now))).scalars().all()
        for d in due:
            accs = await accounts_for(s, d.character_id)
            if not accs:
                d.status, d.error = "failed", "no_accounts"
                await s.commit()
                await _notify_failed(ctx, d, [("", "no_accounts")])
                continue
            for a in accs:
                try:
                    async with s.begin_nested():
                        s.add(Publication(draft_id=d.id, account_id=a.id, user_id=d.user_id, platform=a.platform,
                                          created_ms=now))
                except IntegrityError:
                    pass  # already there: never two posts for one (draft, platform)
            d.status = "publishing"
            n += 1
        await s.commit()
    return n


# ---------- step 2: run publications ----------

async def _claim(ctx, now: int) -> int | None:
    async with ctx.db.sessions() as s:
        ids = (await s.execute(select(Publication.id).where(or_(
            Publication.status.in_(("pending", "retry")) & (Publication.next_attempt_ms <= now),
            (Publication.status == "publishing") & (Publication.claimed_ms < now - STUCK_MS),  # worker died
        )).order_by(Publication.id).limit(10))).scalars().all()
        for pid in ids:
            res = await s.execute(update(Publication).where(
                Publication.id == pid, or_(Publication.status.in_(("pending", "retry")),
                                           Publication.claimed_ms < now - STUCK_MS))
                .values(status="publishing", claimed_ms=now, attempts=Publication.attempts + 1))
            if res.rowcount == 1:
                await s.commit()
                return pid
    return None


async def run_one(ctx, pid: int) -> None:
    async with ctx.db.sessions() as s:
        p = await s.get(Publication, pid)
        d = await s.get(Draft, p.draft_id)
        ch = await s.get(Character, d.character_id)
        a = await s.get(Account, p.account_id)
        pub = ctx.publishers.get(p.platform)
        state = dict(p.state or {})
        try:
            if pub is None:
                raise PublishError("platform_not_supported")
            if a is None:
                raise PublishError("no_accounts")
            if a.status == "expired":
                raise PublishError("token_expired", account_broken=False)
            media = [Media(external_url(ctx, sl["key"]) if pub.needs_public_urls else "",
                           None if pub.needs_public_urls else await ctx.storage.get(sl["key"])) for sl in d.slides]
            res = await pub.publish(creds(ctx, a), Post(media, final_caption(d, ch), d.alt_text), state)
        except PublishError as e:
            p.state = state
            p.error_code, p.error_message = e.code, e.message[:1000]
            if e.account_broken and a is not None:
                a.status, a.last_error = "expired" if e.code == "token_expired" else "error", e.code
            if e.retryable and p.attempts < MAX_ATTEMPTS:
                p.status = "retry"
                p.next_attempt_ms = now_ms() + max(backoff(p.attempts), e.retry_after_ms or 0)
                log.warning("publication %s %s: %s, retry #%s", p.id, p.platform, e.code, p.attempts)
            else:
                p.status = "failed"
                log.warning("publication %s %s failed: %s %s", p.id, p.platform, e.code, e.message)
            await s.commit()
        except Exception as e:  # noqa: BLE001 - unknown error: retry a few times, it may be transient
            log.exception("publication %s crashed", p.id)
            p.state, p.error_code, p.error_message = state, "internal_error", str(e)[:500]
            p.status = "retry" if p.attempts < MAX_ATTEMPTS else "failed"
            p.next_attempt_ms = now_ms() + backoff(p.attempts)
            await s.commit()
        else:
            p.state, p.status, p.external_id, p.permalink = state, "published", res.external_id, res.permalink
            p.published_ms, p.error_code, p.error_message = now_ms(), None, None
            await s.commit()
        await _maybe_finish(ctx, s, d, ch)


async def _maybe_finish(ctx, s: AsyncSession, d: Draft, ch: Character) -> None:
    pubs = list((await s.execute(select(Publication).where(Publication.draft_id == d.id))).scalars())
    if any(p.status in ("pending", "retry", "publishing") for p in pubs) or d.status != "publishing":
        return
    ok = [p for p in pubs if p.status == "published"]
    d.status = "published" if len(ok) == len(pubs) else ("partially_published" if ok else "failed")
    if ok:
        d.published_ms = now_ms()
        remember(ch, d)
    else:
        d.error = pubs[0].error_code if pubs else "no_accounts"
    await s.commit()
    if ok:
        await _notify_published(ctx, s, d, ch, ok)
    failed = [(p.platform, p.error_code) for p in pubs if p.status == "failed"]
    if failed:
        await _notify_failed(ctx, d, failed)


async def process(ctx, limit: int = 20) -> int:
    n = 0
    while n < limit:
        pid = await _claim(ctx, now_ms())
        if pid is None:
            break
        await run_one(ctx, pid)
        n += 1
    return n


# ---------- bot messages ----------

async def _notify_published(ctx, s: AsyncSession, d: Draft, ch: Character, ok: list[Publication]) -> None:
    links = "\n".join(f"• {PLATFORM_NAMES.get(p.platform, p.platform)}: {p.permalink or 'опубликовано'}" for p in ok)
    if ch.autopilot:
        photos = [await ctx.storage.get(sl["key"]) for sl in d.slides]
        text = (f"🤖 <b>{html.escape(ch.name)}</b> опубликовал пост (автопилот)\n\n"
                f"{html.escape(final_caption(d, ch))}\n\n{html.escape(links)}")
        await ctx.notifier.send_album(d.user_id, photos, text, [[Button("🗑 Удалить", f"p:del:{d.id}")]])
    else:
        await ctx.notifier.send(d.user_id, f"✅ <b>{html.escape(ch.name)}</b>: пост опубликован\n{html.escape(links)}")


async def _notify_failed(ctx, d: Draft, failed: list[tuple[str, str | None]]) -> None:
    lines = "\n".join(f"• {PLATFORM_NAMES.get(pl, pl) + ': ' if pl else ''}{error_text(code, pl)}"
                      for pl, code in failed)
    buttons = [[Button("Открыть Purrpost", web_app=ctx.settings.webapp_url)]] if ctx.settings.webapp_url else None
    with contextlib.suppress(Exception):
        await ctx.notifier.send(d.user_id, f"⚠️ Не удалось опубликовать пост:\n{lines}", buttons)


# ---------- deleting (autopilot "Delete" button) ----------

async def delete_post(ctx, s: AsyncSession, d: Draft) -> list[tuple[str, str | None]]:
    """Delete a published post everywhere. Returns [(platform, error code or None)]."""
    out = []
    for p in (await s.execute(select(Publication).where(Publication.draft_id == d.id,
                                                        Publication.status == "published"))).scalars():
        a = await s.get(Account, p.account_id)
        pub = ctx.publishers.get(p.platform)
        try:
            await pub.delete(creds(ctx, a), p.external_id, dict(p.state or {}))
        except PublishError as e:
            out.append((p.platform, e.code))
            continue
        p.status = "deleted"
        out.append((p.platform, None))
    if out and all(err is None for _, err in out):
        d.status = "deleted"
    await s.commit()
    return out


async def handle_callback(ctx, user_id: int, data: str) -> str:
    try:
        _, action, raw = data.split(":")
        did = int(raw)
    except ValueError:
        return "Неизвестная кнопка"
    if action != "del":
        return "Неизвестная кнопка"
    async with ctx.db.sessions() as s:
        d = await s.get(Draft, did)
        if d is None or d.user_id != user_id:
            return "Пост не найден"
        res = await delete_post(ctx, s, d)
    if not res:
        return "Пост уже удалён"
    bad = [f"{PLATFORM_NAMES.get(pl, pl)}: {error_text(err, pl)}" for pl, err in res if err]
    if not bad:
        return "🗑 Пост удалён"
    return "Удалено не везде. " + "; ".join(bad)


# ---------- tokens ----------

async def refresh_tokens(ctx, now: int | None = None) -> int:
    """Long-lived Instagram/Threads tokens last 60 days: refresh them well before they expire."""
    from .crypto import encrypt
    from .oauth import refresh
    now = now or now_ms()
    n = 0
    async with ctx.db.sessions() as s:
        rows = (await s.execute(select(Account).where(
            Account.platform.in_(("instagram", "threads")), Account.status == "ok",
            Account.token_expires_ms < now + REFRESH_BEFORE_MS,
            or_(Account.token_refreshed_ms.is_(None), Account.token_refreshed_ms < now - 86_400_000)))).scalars().all()
        for a in rows:
            try:
                tok = await refresh(ctx.settings, ctx.http, a.platform, decrypt(ctx.settings, a.token_enc), now)
            except PublishError as e:
                a.token_refreshed_ms = now
                if not e.retryable:
                    a.status, a.last_error = "expired", e.code
                    ch = await s.get(Character, a.character_id)
                    await ctx.notifier.send(a.user_id, f"Токен {PLATFORM_NAMES[a.platform]} для "
                                                       f"<b>{html.escape(ch.name)}</b> истёк — переподключите "
                                                       "аккаунт в приложении, иначе посты не выйдут.")
                continue
            a.token_enc, a.token_expires_ms, a.token_refreshed_ms = encrypt(ctx.settings, tok.access_token), \
                tok.expires_ms, now
            n += 1
        await s.commit()
    return n
