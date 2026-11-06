from datetime import datetime, timedelta, timezone

from app.services.approval import handle_callback, handle_reply

from .conftest import OWNER, auth, invite_user, ready_character, run_jobs
from .test_pipeline import generate


async def test_bot_approve(client, ctx):
    _, d = await generate(client, ctx)
    msg = ctx.notifier.last(OWNER)
    assert [b.data for row in msg.buttons for b in row] == [
        f"d:ok:{d['id']}", f"d:regen:{d['id']}", f"d:img:{d['id']}", f"d:edit:{d['id']}", f"d:skip:{d['id']}"]
    text = await handle_callback(ctx, OWNER, f"d:ok:{d['id']}")
    assert text.startswith("✅ Запланировано на")
    d2 = (await client.get(f"/api/drafts/{d['id']}", headers=auth(OWNER))).json()
    assert d2["status"] == "scheduled" and d2["approved_ms"]
    # second press, or a stale button
    assert await handle_callback(ctx, OWNER, f"d:ok:{d['id']}") == "С этим черновиком уже что-то сделали"
    assert await handle_callback(ctx, OWNER, "d:ok:999") == "Черновик не найден"
    assert await handle_callback(ctx, OWNER, "garbage") == "Неизвестная кнопка"


async def test_bot_buttons_respect_ownership(client, ctx):
    await invite_user(client, 70)
    _, d = await generate(client, ctx)
    assert await handle_callback(ctx, 70, f"d:ok:{d['id']}") == "Черновик не найден"
    assert await handle_callback(ctx, 70, f"d:skip:{d['id']}") == "Черновик не найден"


async def test_bot_regenerate_all_and_images(client, ctx):
    ch, d = await generate(client, ctx)
    old_caption, old_url = d["caption"], d["slides"][0]["url"]
    assert (await handle_callback(ctx, OWNER, f"d:img:{d['id']}")).startswith("🖼")
    await run_jobs(ctx)
    d2 = (await client.get(f"/api/drafts/{d['id']}", headers=auth(OWNER))).json()
    assert d2["status"] == "pending_review" and d2["caption"] == old_caption and d2["slides"][0]["url"] != old_url
    assert ctx.notifier.last(OWNER).photos == 3  # a fresh draft message

    ctx.fakes["llm"].queue["post_plan"].append(
        '{"idea": "A new idea", "slides": [{"scene": "the cat on a roof"}], "caption": "Fresh", '
        '"hashtags": ["#a", "#b", "#c", "#d", "#e"]}')
    assert (await handle_callback(ctx, OWNER, f"d:regen:{d['id']}")).startswith("🔄")
    await run_jobs(ctx)
    d3 = (await client.get(f"/api/drafts/{d['id']}", headers=auth(OWNER))).json()
    assert d3["caption"] == "Fresh" and len(d3["slides"]) == 1 and d3["status"] == "pending_review"


async def test_bot_edit_caption_by_reply(client, ctx):
    _, d = await generate(client, ctx)
    draft_msg = ctx.notifier.last(OWNER).message_id
    await handle_callback(ctx, OWNER, f"d:edit:{d['id']}")
    prompt_msg = ctx.notifier.last(OWNER)
    assert "Ответьте на это сообщение" in prompt_msg.text
    assert await handle_reply(ctx, OWNER, prompt_msg.message_id, "  New words from the Don.  ") == "ok"
    d2 = (await client.get(f"/api/drafts/{d['id']}", headers=auth(OWNER))).json()
    assert d2["caption"] == "New words from the Don." and d2["final_caption"].startswith("New words")
    assert "Подпись обновлена" in ctx.notifier.last(OWNER).text
    # replying straight to the draft message works too
    assert await handle_reply(ctx, OWNER, draft_msg, "Second edit") == "ok"
    # replies to unrelated messages are ignored; someone else's reply finds nothing
    assert await handle_reply(ctx, OWNER, 123456, "hi") is None
    assert await handle_reply(ctx, 70, draft_msg, "hack") is None
    assert await handle_reply(ctx, OWNER, draft_msg, "   ") == "Подпись пустая или длиннее 2000 символов"


async def test_skip_resets_streak(client, ctx):
    ch, d = await generate(client, ctx)
    await handle_callback(ctx, OWNER, f"d:ok:{d['id']}")
    _, d2 = await generate(client, ctx, char=ch)
    c = (await client.get(f"/api/characters/{ch['id']}", headers=auth(OWNER))).json()
    assert c["approved_streak"] == 1
    assert (await handle_callback(ctx, OWNER, f"d:skip:{d2['id']}")) == "🗑 Пропущено"
    c = (await client.get(f"/api/characters/{ch['id']}", headers=auth(OWNER))).json()
    assert c["approved_streak"] == 0


async def test_app_edit_reorder_approve(client, ctx):
    _, d = await generate(client, ctx)
    urls = [sl["url"] for sl in d["slides"]]
    r = await client.patch(f"/api/drafts/{d['id']}", headers=auth(OWNER),
                           json={"caption": "Edited", "hashtags": ["cats", "#Cats", "#don"], "order": [2, 0, 1]})
    assert r.status_code == 200
    d2 = r.json()
    assert [sl["url"] for sl in d2["slides"]] == [urls[2], urls[0], urls[1]]
    assert d2["hashtags"] == ["#cats", "#don"] and d2["caption"] == "Edited"
    assert (await client.patch(f"/api/drafts/{d['id']}", headers=auth(OWNER), json={"order": [0, 0, 1]})).json()[
        "detail"] == "bad_order"
    r = await client.post(f"/api/drafts/{d['id']}/approve", headers=auth(OWNER))
    assert r.json()["status"] == "scheduled"
    r = await client.post(f"/api/drafts/{d['id']}/unschedule", headers=auth(OWNER))
    assert r.json()["status"] == "pending_review"
    r = await client.post(f"/api/drafts/{d['id']}/skip", headers=auth(OWNER))
    assert r.json()["status"] == "skipped"
    assert (await client.post(f"/api/drafts/{d['id']}/approve", headers=auth(OWNER))).status_code == 400


async def test_calendar(client, ctx):
    ch = await ready_character(client, ctx, OWNER)
    await client.patch(f"/api/characters/{ch['id']}/settings", headers=auth(OWNER),
                       json={"schedule": {"times": ["18:00"], "days": list(range(7)), "tz": "UTC", "lead_hours": 6}})
    _, d = await generate(client, ctx, char=ch)
    now = datetime.now(timezone.utc)
    frm = int(now.timestamp() * 1000)
    to = int((now + timedelta(days=7)).timestamp() * 1000)
    cal = (await client.get(f"/api/calendar?from_ms={frm}&to_ms={to}", headers=auth(OWNER))).json()
    assert [x["id"] for x in cal["drafts"]] == [d["id"]] and cal["drafts"][0]["thumb"]
    assert len(cal["planned"]) in (6, 7) and d["slot_ms"] not in [p["slot_ms"] for p in cal["planned"]]
    r = await client.get(f"/api/calendar?from_ms=0&to_ms={to}", headers=auth(OWNER))
    assert r.status_code == 400
