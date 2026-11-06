"""Worker process: `python -m app.worker`. Runs the background jobs loop (Railway: a separate service)."""

from __future__ import annotations

import asyncio
import logging

from . import jobs
from .config import get_settings
from .db import Database
from .main import build_ctx

log = logging.getLogger("purrpost.worker")


async def main() -> None:
    settings = get_settings()
    db = Database(settings.db_url)
    if settings.auto_create_schema:
        await db.create_schema()
    bot = None
    if settings.bot_token:
        from .bot import create_bot
        bot = create_bot(settings)
    ctx = build_ctx(settings, db, bot)
    log.info("worker started, every %ss", settings.worker_interval_sec)
    try:
        await jobs.loop(ctx)
    finally:
        if bot:
            await bot.session.close()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
