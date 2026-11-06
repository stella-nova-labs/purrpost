"""Fill a local database with a realistic demo: the owner with Don Whiskers and tilted (fake looks, LoRA,
connected accounts, a month of published posts with metrics and follower growth), a friend on an invite with
their own cat, drafts waiting for review. Fake providers only: nothing leaves the machine.

    cd backend && DEV_AUTH=1 DEV_FAKE_PROVIDERS=1 OWNER_ID=1 .venv/bin/python scripts/demo_seed.py
then start uvicorn on the same DATABASE_URL and open http://localhost:8000/?dev=1 (owner) or ?dev=2 (friend).
"""

from __future__ import annotations

import asyncio
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy import select, text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import jobs  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import Database  # noqa: E402
from app.main import build_ctx, create_app  # noqa: E402
from app.models import AccountStat, Account, Draft  # noqa: E402

OWNER, FRIEND = 1, 2
DAY = 86_400_000


def h(uid: int) -> dict:
    return {"Authorization": f"tma dev:{uid}"}


async def tick(ctx, n: int = 4) -> None:
    for _ in range(n):
        await jobs.tick(ctx)


async def ready(c, ctx, uid: int, slug: str, pick: int) -> dict:
    ch = (await c.post(f"/api/characters/from-template/{slug}", headers=h(uid))).json()
    await tick(ctx)
    ch = (await c.get(f"/api/characters/{ch['id']}", headers=h(uid))).json()
    await c.post(f"/api/characters/{ch['id']}/choose", json={"image_id": ch["candidates"][pick]["id"]}, headers=h(uid))
    await tick(ctx)
    await c.post(f"/api/characters/{ch['id']}/train", headers=h(uid))
    await tick(ctx)
    return (await c.post(f"/api/characters/{ch['id']}/confirm", json={"ok": True}, headers=h(uid))).json()


async def connect(c, cid: int, platform: str, uid: int = OWNER) -> None:
    if platform == "telegram":
        await c.post(f"/api/characters/{cid}/accounts/telegram", json={"channel": "@purrpost_demo"}, headers=h(uid))
        return
    url = urlparse((await c.get(f"/api/oauth/{platform}/start?character_id={cid}", headers=h(uid))).json()["url"])
    await c.get(f"{url.path}?{url.query}")


async def main() -> None:
    s = get_settings()
    if not (s.dev_fake_providers and s.dev_auth and s.owner_id == OWNER):
        raise SystemExit("run with DEV_AUTH=1 DEV_FAKE_PROVIDERS=1 OWNER_ID=1")
    db = Database(s.db_url)
    await db.create_schema()
    app = create_app(s)
    app.state.db, app.state.bot_username = db, "purrpost_bot"
    ctx = app.state.ctx = build_ctx(s, db)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://demo") as c:
        await c.get("/api/me", headers=h(OWNER))
        await c.patch(f"/api/admin/users/{OWNER}", json={"budget_usd": 50}, headers=h(OWNER))  # room for a month of demo posts
        don = await ready(c, ctx, OWNER, "don-whiskers", 1)
        tilted = await ready(c, ctx, OWNER, "tilted", 2)
        for p in ("instagram", "telegram"):
            await connect(c, don["id"], p)
        await connect(c, tilted["id"], "instagram")
        await connect(c, tilted["id"], "threads")

        # a month of posts: generate, approve, move into the past, publish, collect metrics
        for ch, count in ((don, 9), (tilted, 6)):
            for _ in range(count):
                d = (await c.post(f"/api/characters/{ch['id']}/generate", json={}, headers=h(OWNER))).json()
                await tick(ctx, 2)
                await c.post(f"/api/drafts/{d['id']}/approve", headers=h(OWNER))
        async with db.sessions() as ss:
            rows = (await ss.execute(select(Draft).where(Draft.status == "scheduled").order_by(Draft.id))).scalars().all()
            now = int(datetime.now(timezone.utc).timestamp() * 1000)
            for i, d in enumerate(rows):
                d.slot_ms = now - (len(rows) - i) * 2 * DAY
            await ss.commit()
        await tick(ctx, 3)
        async with db.sessions() as ss:
            await ss.execute(text("update publications set published_ms = (select slot_ms from drafts "
                                  "where drafts.id = publications.draft_id) + 600000"))
            await ss.execute(text("update drafts set published_ms = slot_ms + 600000 where published_ms is not null"))
            await ss.commit()
        await tick(ctx, 3)
        # follower growth for the chart
        async with db.sessions() as ss:
            await ss.execute(text("delete from account_stats"))
            rng = random.Random(7)
            for a in (await ss.execute(select(Account))).scalars():
                base = rng.randint(300, 900)
                for k in range(30, -1, -1):
                    day = (datetime.now(timezone.utc) - timedelta(days=k)).strftime("%Y-%m-%d")
                    base += rng.randint(5, 40)
                    ss.add(AccountStat(account_id=a.id, day=day, followers=base, fetched_ms=now))
            await ss.commit()

        # fresh drafts waiting for review (one flagged by QA), and one scheduled for tomorrow
        d1 = (await c.post(f"/api/characters/{don['id']}/generate", json={"trend": "Halloween leftovers"},
                           headers=h(OWNER))).json()
        bad = ('{"anatomy_ok": false, "matches_reference": true, "text_artifacts": true, '
               '"logos_or_known_characters": false, "weapons": false, "issues": ["garbled sign in the background"], '
               '"score": 0.4}')
        await tick(ctx, 2)
        ctx.fakes["llm"].queue["qa"] += [bad] * 6
        d2 = (await c.post(f"/api/characters/{tilted['id']}/generate", json={}, headers=h(OWNER))).json()
        await tick(ctx, 2)
        d3 = (await c.post(f"/api/characters/{tilted['id']}/generate", json={}, headers=h(OWNER))).json()
        await tick(ctx, 2)
        await c.post(f"/api/drafts/{d3['id']}/approve", headers=h(OWNER))
        async with db.sessions() as ss:
            (await ss.get(Draft, d3["id"])).slot_ms = now + DAY
            await ss.commit()

        # a friend on an invite with a cat of their own
        code = (await c.post("/api/admin/invites", json={"max_uses": 3, "note": "friends"}, headers=h(OWNER))).json()["code"]
        await c.post("/api/invite/redeem", json={"code": code}, headers=h(FRIEND))
        card = (await c.post("/api/characters/suggest", json={"idea": "a sleepy space cat who runs a bakery on Mars"},
                             headers=h(FRIEND))).json()
        card.update({"name": "Biscuit", "handle": "biscuit.on.mars"})
        cb = (await c.post("/api/characters", json=card, headers=h(FRIEND))).json()
        await c.post(f"/api/characters/{cb['id']}/candidates", json={"count": 8, "extra": ""}, headers=h(FRIEND))
        await tick(ctx, 2)
        await c.post("/api/admin/invites", json={"max_uses": 1, "note": "for Sasha"}, headers=h(OWNER))
        print(f"done: don={don['id']} tilted={tilted['id']} review={d1['id']},{d2['id']} invite={code}")
    await ctx.http.aclose()
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
