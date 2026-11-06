import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings  # noqa: E402
from app.db import Database  # noqa: E402
from app.main import build_ctx, create_app  # noqa: E402

BOT_TOKEN = "123456:TEST-TOKEN"
OWNER = 1


@pytest.fixture
def settings(tmp_path):
    return Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 't.db'}", dev_auth=True, bot_token=BOT_TOKEN,
                    owner_id=OWNER, dev_fake_providers=True, media_dir=str(tmp_path / "media"),
                    encryption_key="", webapp_url="https://purrpost.test")


@pytest.fixture
async def app(settings):
    a = create_app(settings)
    db = Database(settings.db_url)
    await db.create_schema()
    a.state.db = db
    a.state.bot_username = "purrpost_test_bot"
    a.state.ctx = build_ctx(settings, db)
    yield a
    await db.close()


@pytest.fixture
def ctx(app):
    return app.state.ctx


@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


def auth(uid: int, start_param: str | None = None) -> dict:
    return {"Authorization": f"tma dev:{uid}" + (f":{start_param}" if start_param else "")}


async def invite_user(client, uid: int) -> None:
    """Owner creates a code, user `uid` redeems it."""
    r = await client.post("/api/admin/invites", json={"max_uses": 1}, headers=auth(OWNER))
    assert r.status_code == 200, r.text
    r = await client.post("/api/invite/redeem", json={"code": r.json()["code"]}, headers=auth(uid))
    assert r.status_code == 200, r.text


async def run_jobs(ctx, rounds: int = 5) -> None:
    """What the worker does: process the queue and poll trainings until nothing is left."""
    from app import jobs
    for _ in range(rounds):
        await jobs.tick(ctx)


async def ready_character(client, ctx, uid: int, slug: str = "don-whiskers") -> dict:
    """Create a character from a template and walk it through the whole wizard (fake providers)."""
    ch = (await client.post(f"/api/characters/from-template/{slug}", headers=auth(uid))).json()
    await run_jobs(ctx)
    ch = (await client.get(f"/api/characters/{ch['id']}", headers=auth(uid))).json()
    ch = (await client.post(f"/api/characters/{ch['id']}/choose", json={"image_id": ch["candidates"][0]["id"]},
                            headers=auth(uid))).json()
    await run_jobs(ctx)
    assert (await client.post(f"/api/characters/{ch['id']}/train", headers=auth(uid))).status_code == 200
    await run_jobs(ctx)
    r = await client.post(f"/api/characters/{ch['id']}/confirm", json={"ok": True}, headers=auth(uid))
    assert r.status_code == 200, r.text
    return r.json()
