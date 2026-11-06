from sqlalchemy import text

from app.models import Character
from app.services import metrics
from app.services.approval import handle_callback

from .conftest import OWNER, auth, invite_user, ready_character, run_jobs
from .test_pipeline import generate
from .test_publishing import approved_due, connect


async def test_autopilot_unlocks_after_streak(client, ctx):
    ch = await ready_character(client, ctx, OWNER)
    await invite_user(client, 95)
    friend = await ready_character(client, ctx, 95, "tilted")
    r = await client.patch(f"/api/characters/{friend['id']}/settings", json={"autopilot": True}, headers=auth(95))
    assert r.status_code == 400 and r.json()["detail"] == "autopilot_locked"

    async with ctx.db.sessions() as s:
        (await s.get(Character, ch["id"])).approved_streak = 9
        await s.commit()
    _, d = await generate(client, ctx, char=ch)
    await handle_callback(ctx, OWNER, f"d:ok:{d['id']}")
    c = (await client.get(f"/api/characters/{ch['id']}", headers=auth(OWNER))).json()
    assert c["autopilot"] and c["approved_streak"] == 10 and c["autopilot_unlocked"]
    assert "включаю автопилот" in ctx.notifier.last(OWNER).text
    _, d2 = await generate(client, ctx, char=ch)
    assert d2["status"] == "scheduled"  # no review any more

    # the user can switch it off; then on again (still unlocked)
    r = await client.patch(f"/api/characters/{ch['id']}/settings", json={"autopilot": False}, headers=auth(OWNER))
    assert r.json()["autopilot"] is False
    # the owner switches it on manually for a friend
    r = await client.patch(f"/api/admin/characters/{friend['id']}", json={"autopilot": True}, headers=auth(OWNER))
    assert r.json() == {"id": friend["id"], "autopilot": True}
    assert (await client.patch(f"/api/admin/characters/{friend['id']}", json={"autopilot": True},
                               headers=auth(95))).status_code == 403


async def test_metrics_and_dashboard(client, ctx):
    ch, d = await approved_due(client, ctx, ("instagram", "telegram"))
    await run_jobs(ctx)
    assert await metrics.collect(ctx) == 0  # too early
    async with ctx.db.sessions() as s:
        await s.execute(text("update publications set published_ms = published_ms - 25 * 3600000"))
        await s.commit()
    assert await metrics.collect(ctx) == 2  # 24h for both platforms
    assert await metrics.collect(ctx) == 0
    async with ctx.db.sessions() as s:
        await s.execute(text("update publications set published_ms = published_ms - 7 * 86400000"))
        await s.commit()
    assert await metrics.collect(ctx) == 2
    assert await metrics.account_stats(ctx) == 0  # the worker tick already took today's followers: once a day

    dash = (await client.get(f"/api/dashboard?character_id={ch['id']}", headers=auth(OWNER))).json()
    post = dash["posts"][0]
    assert post["id"] == d["id"] and post["window"] == "7d" and post["metrics"]["reach"] > 0
    assert set(post["platforms"]) == {"instagram", "telegram"}
    assert dash["totals"]["posts"] == 1 and dash["totals"]["avg_reach"] == post["metrics"]["reach"]
    assert set(dash["totals"]["followers"]) == {"instagram", "telegram"} and len(dash["followers_series"]) == 1
    assert dash["rubrics"][0]["posts"] == 1
    assert dash["characters"][0]["spend_month"] > 0 and dash["budget"]["spent"] > 0


async def test_dashboard_is_per_user(client, ctx):
    await approved_due(client, ctx)
    await run_jobs(ctx)
    await invite_user(client, 96)
    dash = (await client.get("/api/dashboard", headers=auth(96))).json()
    assert dash["posts"] == [] and dash["characters"] == [] and dash["totals"]["spend_month"] == 0
    other = (await client.get("/api/characters", headers=auth(OWNER))).json()[0]["id"]
    assert (await client.get(f"/api/dashboard?character_id={other}", headers=auth(96))).status_code == 404


async def test_admin_overview(client, ctx):
    await invite_user(client, 97)
    await ready_character(client, ctx, 97, "tilted")
    ov = (await client.get("/api/admin/overview", headers=auth(OWNER))).json()
    friend = next(u for u in ov["users"] if u["id"] == 97)
    assert friend["characters"] == 1 and friend["spent_usd"] > 2  # LoRA training + images
    assert ov["characters"][0]["autopilot"] is False and ov["total_spent_usd"] >= friend["spent_usd"]
    assert (await client.get("/api/admin/overview", headers=auth(97))).status_code == 403


async def test_metrics_errors_dont_loop(client, ctx):
    from app.publishers.base import PublishError
    await approved_due(client, ctx)
    await run_jobs(ctx)

    async def broken(*a, **kw):
        raise PublishError("rate_limited", retryable=True)

    ctx.publishers["instagram"].metrics = broken
    async with ctx.db.sessions() as s:
        await s.execute(text("update publications set published_ms = published_ms - 25 * 3600000"))
        await s.commit()
    assert await metrics.collect(ctx) == 0  # will retry
    async with ctx.db.sessions() as s:
        await s.execute(text("update publications set published_ms = published_ms - 2 * 86400000"))
        await s.commit()
    assert await metrics.collect(ctx) == 1  # gave up on 24h, recorded as an error
