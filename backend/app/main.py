from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

from . import jobs
from .api.admin import router as admin_router
from .api.me import router as me_router
from .config import Settings, get_settings
from .context import Ctx
from .db import Database
from .services.notify import BotNotifier, MemoryNotifier

log = logging.getLogger("purrpost")

STATIC_CANDIDATES = [Path(__file__).resolve().parent.parent / "static",
                     Path(__file__).resolve().parents[2] / "frontend" / "dist"]

ROUTERS = [me_router, admin_router]


def build_ctx(settings: Settings, db: Database, bot=None) -> Ctx:
    return Ctx(settings=settings, db=db, bot=bot,
               notifier=BotNotifier(bot) if bot is not None else MemoryNotifier())


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = Database(settings.db_url)
        if settings.auto_create_schema:
            await db.create_schema()
        app.state.db = db
        app.state.bot_username = None
        app.state.dp = None
        polling = None
        bot = None
        if settings.bot_token and settings.bot_mode != "off":
            from .bot import create_bot
            bot = create_bot(settings)
        ctx = build_ctx(settings, db, bot)
        app.state.ctx = ctx
        if bot is not None:
            from .bot import create_dispatcher, setup_menu
            dp = create_dispatcher(ctx)
            app.state.bot_username = (await bot.get_me()).username
            await setup_menu(bot, settings)
            if settings.bot_mode == "webhook":
                app.state.dp = dp
                await bot.set_webhook(settings.webapp_url.rstrip("/") + "/bot/webhook",
                                      secret_token=settings.webhook_secret or None,
                                      allowed_updates=dp.resolve_used_update_types())
            else:
                await bot.delete_webhook()
                polling = asyncio.create_task(dp.start_polling(bot, handle_signals=False))
            log.info("bot @%s started (%s)", app.state.bot_username, settings.bot_mode)
        worker = asyncio.create_task(jobs.loop(ctx)) if settings.run_worker else None
        try:
            yield
        finally:
            for t in [polling, worker]:
                if t:
                    t.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await t
            if bot:
                await bot.session.close()
            await db.close()

    app = FastAPI(title="Purrpost", lifespan=lifespan, docs_url="/api/docs" if settings.dev_auth else None,
                  redoc_url=None, openapi_url="/api/openapi.json" if settings.dev_auth else None)
    app.state.settings = settings
    for r in ROUTERS:
        app.include_router(r)

    @app.get("/api/health", include_in_schema=False)
    async def health() -> dict:
        return {"ok": True}

    @app.post("/bot/webhook", include_in_schema=False)
    async def webhook(request: Request) -> dict:
        dp = request.app.state.dp
        if dp is None:
            raise HTTPException(404)
        if settings.webhook_secret and request.headers.get(
                "x-telegram-bot-api-secret-token") != settings.webhook_secret:
            raise HTTPException(403)
        from aiogram.types import Update
        bot = request.app.state.ctx.bot
        await dp.feed_update(bot, Update.model_validate(await request.json(), context={"bot": bot}))
        return {"ok": True}

    static = next((p for p in STATIC_CANDIDATES if (p / "index.html").exists()), None)
    if static is not None:
        index = static / "index.html"

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str) -> FileResponse:
            if path.startswith(("api/", "media/", "oauth/")):
                raise HTTPException(404)
            f = (static / path).resolve()
            if path and f.is_file() and static.resolve() in f.parents:
                return FileResponse(f)
            return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
# httpx logs full URLs, which may carry tokens (Graph API access_token): keep them out of the logs
logging.getLogger("httpx").setLevel(logging.WARNING)
app = create_app()
