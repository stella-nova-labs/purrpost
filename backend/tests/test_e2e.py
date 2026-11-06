"""The acceptance path on fake providers: invite -> wizard -> draft -> approval in the bot -> (fake) publishing ->
dashboard, plus a second user who sees only their own things and is stopped by their budget."""

from sqlalchemy import text

from app.models import Draft, User
from app.services import metrics
from app.services.approval import handle_callback

from .conftest import OWNER, auth, run_jobs
from .test_publishing import connect


async def test_acceptance_path(client, ctx):
    # the owner invites a friend
    code = (await client.post("/api/admin/invites", json={"max_uses": 1, "note": "Sasha"}, headers=auth(OWNER))).json()["code"]
    FRIEND = 200
    assert (await client.get("/api/characters", headers=auth(FRIEND))).status_code == 403
    assert (await client.get("/api/me", headers=auth(FRIEND, f"inv_{code}"))).json()["user"]["is_active"]

    # the friend creates a character from one phrase and walks the wizard
    card = (await client.post("/api/characters/suggest", json={"idea": "a cat detective in rainy London"},
                              headers=auth(FRIEND))).json()
    card.update(name="Inspector Purrcy", handle="inspector.purrcy")
    ch = (await client.post("/api/characters", json=card, headers=auth(FRIEND))).json()
    await client.post(f"/api/characters/{ch['id']}/candidates", json={"count": 10}, headers=auth(FRIEND))
    await run_jobs(ctx)
    ch = (await client.get(f"/api/characters/{ch['id']}", headers=auth(FRIEND))).json()
    assert len(ch["candidates"]) == 10
    await client.post(f"/api/characters/{ch['id']}/choose", json={"image_id": ch["candidates"][4]["id"]}, headers=auth(FRIEND))
    await run_jobs(ctx)
    ch = (await client.get(f"/api/characters/{ch['id']}", headers=auth(FRIEND))).json()
    for img in ch["refs"][:2]:  # drops a couple of bad references
        await client.delete(f"/api/characters/{ch['id']}/images/{img['id']}", headers=auth(FRIEND))
    await client.post(f"/api/characters/{ch['id']}/train", headers=auth(FRIEND))
    await run_jobs(ctx)
    assert any("LoRA" in m.text for m in ctx.notifier.sent if m.chat_id == FRIEND)
    ch = (await client.post(f"/api/characters/{ch['id']}/confirm", json={"ok": True}, headers=auth(FRIEND))).json()
    assert ch["status"] == "ready"

    # connects Instagram and a Telegram channel
    await connect(client, ch["id"], "instagram", FRIEND)
    await client.post(f"/api/characters/{ch['id']}/accounts/telegram", json={"channel": "@purrcy"}, headers=auth(FRIEND))

    # the planner makes a draft within the lead time; the bot sends it for approval
    await client.patch(f"/api/characters/{ch['id']}/settings", headers=auth(FRIEND), json={
        "schedule": {"times": ["00:00", "06:00", "12:00", "18:00"], "days": list(range(7)), "tz": "UTC", "lead_hours": 6}})
    await run_jobs(ctx)
    drafts = (await client.get("/api/drafts?status=pending_review", headers=auth(FRIEND))).json()
    assert len(drafts) >= 1
    d = drafts[0]
    msg = next(m for m in reversed(ctx.notifier.sent) if m.chat_id == FRIEND and m.photos)
    assert msg.buttons[0][0].data == f"d:ok:{d['id']}"

    # approval in the bot, the slot arrives, publishing (fake)
    assert (await handle_callback(ctx, FRIEND, f"d:ok:{d['id']}")).startswith("✅")
    async with ctx.db.sessions() as s:
        (await s.get(Draft, d["id"])).slot_ms = 0
        await s.commit()
    await run_jobs(ctx)
    d = (await client.get(f"/api/drafts/{d['id']}", headers=auth(FRIEND))).json()
    assert d["status"] == "published" and {p["platform"] for p in d["publications"]} == {"instagram", "telegram"}
    assert all(p["permalink"] for p in d["publications"])

    # metrics a day later -> dashboard
    async with ctx.db.sessions() as s:
        await s.execute(text("update publications set published_ms = published_ms - 25 * 3600000"))
        await s.commit()
    await metrics.collect(ctx)
    dash = (await client.get("/api/dashboard", headers=auth(FRIEND))).json()
    assert dash["posts"][0]["metrics"]["reach"] > 0 and dash["budget"]["spent"] > 0

    # the owner sees nothing of the friend's, but sees the friend's spend
    assert (await client.get("/api/characters", headers=auth(OWNER))).json() == []
    assert (await client.get(f"/api/drafts/{d['id']}", headers=auth(OWNER))).status_code == 404
    users = (await client.get("/api/admin/users", headers=auth(OWNER))).json()
    friend_row = next(u for u in users if u["id"] == FRIEND)
    owner_row = next(u for u in users if u["id"] == OWNER)
    assert friend_row["spent_usd"] > 2 and owner_row["spent_usd"] == 0

    # the friend's budget runs out -> generation stops, the bot says so once
    async with ctx.db.sessions() as s:
        (await s.get(User, FRIEND)).budget_usd = 1
        await s.commit()
    r = await client.post(f"/api/characters/{ch['id']}/generate", json={}, headers=auth(FRIEND))
    await run_jobs(ctx)
    d2 = (await client.get(f"/api/drafts/{r.json()['id']}", headers=auth(FRIEND))).json()
    assert d2["status"] == "failed" and d2["error"] == "budget_exceeded"
    assert sum("Бюджет на этот месяц закончился" in m.text for m in ctx.notifier.sent if m.chat_id == FRIEND) == 1
    assert (await client.get("/api/me", headers=auth(FRIEND))).json()["budget"]["exhausted"]


async def test_no_secrets_in_api_responses(client, ctx):
    """Tokens and keys never reach the client, in any response we serve."""
    await client.put("/api/me/keys", json={"fal": "fal-SECRET-KEY-123456", "anthropic": "sk-ant-SECRET-999999"},
                     headers=auth(OWNER))
    ch = (await client.post("/api/characters", json={"name": "A", "handle": "a"}, headers=auth(OWNER))).json()
    await connect(client, ch["id"])
    bodies = []
    for path in ("/api/me", "/api/me/keys", f"/api/characters/{ch['id']}", f"/api/characters/{ch['id']}/accounts",
                 "/api/admin/users", "/api/admin/overview", "/api/dashboard"):
        bodies.append((await client.get(path, headers=auth(OWNER))).text)
    blob = "\n".join(bodies)
    for secret in ("SECRET-KEY", "SECRET-999", "fake-token", "token_enc", "fal_key_enc"):
        assert secret not in blob
