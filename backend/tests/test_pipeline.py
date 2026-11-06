import json

from sqlalchemy import select

from app.models import Character, Draft, Usage
from app.services.drafts import draft_message

from .conftest import OWNER, auth, invite_user, ready_character, run_jobs

BAD_QA = json.dumps({"anatomy_ok": False, "matches_reference": True, "text_artifacts": False,
                     "logos_or_known_characters": False, "weapons": False, "issues": ["five legs"], "score": 0.3})


async def generate(client, ctx, uid=OWNER, char=None, trend=None):
    ch = char or await ready_character(client, ctx, uid)
    r = await client.post(f"/api/characters/{ch['id']}/generate", json={"trend": trend}, headers=auth(uid))
    assert r.status_code == 200, r.text
    await run_jobs(ctx)
    return ch, (await client.get(f"/api/drafts/{r.json()['id']}", headers=auth(uid))).json()


async def test_draft_generated_and_sent_for_review(client, ctx):
    ch, d = await generate(client, ctx, trend="Halloween costumes")
    assert d["status"] == "pending_review" and d["qa_ok"]
    assert len(d["slides"]) == 3 and all(sl["ok"] for sl in d["slides"])
    assert 5 <= len(d["hashtags"]) <= 15 and all(h.startswith("#") for h in d["hashtags"])
    assert "(Halloween costumes)" in d["idea"]
    assert d["final_caption"].endswith("🤖 AI character") and "#aicat" in d["final_caption"]
    msg = ctx.notifier.last(OWNER)
    assert msg.photos == 3 and "черновик" in msg.text and msg.buttons[0][0].data == f"d:ok:{d['id']}"
    # the bible and the rubric went to Claude as data blocks
    task, sent = next(c for c in ctx.fakes["llm"].calls if c[0] == "post_plan")
    assert '<user_data name="character_bible">' in sent and "Don Whiskers" in sent
    # usage written per character
    async with ctx.db.sessions() as s:
        kinds = {u.kind for u in (await s.execute(select(Usage).where(Usage.character_id == ch["id"]))).scalars()}
    assert {"llm.post_plan", "llm.qa", "image.lora"} <= kinds


async def test_qa_failure_regenerates_then_passes(client, ctx):
    ch = await ready_character(client, ctx, OWNER)
    calls = len([c for c in ctx.fakes["llm"].calls if c[0] == "qa"])
    ctx.fakes["llm"].queue["qa"] += [BAD_QA, BAD_QA]  # both variants of the first slide fail in round 1
    _, d = await generate(client, ctx, char=ch)
    assert d["status"] == "pending_review" and d["slides"][0]["ok"]
    async with ctx.db.sessions() as s:
        draft = await s.get(Draft, d["id"])
    assert draft.slides[0]["attempts"] == 2 and draft.slides[1]["attempts"] == 1
    assert len([c for c in ctx.fakes["llm"].calls if c[0] == "qa"]) - calls == 2 + 2 + 2 + 2


async def test_qa_gives_up_after_two_regenerations(client, ctx):
    ch = await ready_character(client, ctx, OWNER)
    ctx.fakes["llm"].queue["qa"] += [BAD_QA] * 6  # first slide: 3 rounds x 2 variants
    _, d = await generate(client, ctx, char=ch)
    assert d["status"] == "needs_review" and not d["qa_ok"]
    assert not d["slides"][0]["ok"] and d["slides"][0]["issues"] == ["five legs"] and d["slides"][1]["ok"]
    assert "Нужна проверка" in ctx.notifier.last(OWNER).text


async def test_autopilot_schedules_directly(client, ctx):
    ch = await ready_character(client, ctx, OWNER)
    async with ctx.db.sessions() as s:
        (await s.get(Character, ch["id"])).autopilot = True
        await s.commit()
    before = len(ctx.notifier.sent)
    _, d = await generate(client, ctx, char=ch)
    assert d["status"] == "scheduled" and d["approved_ms"]
    assert len(ctx.notifier.sent) == before  # nothing to approve


async def test_broken_llm_json_fails_draft(client, ctx):
    ch = await ready_character(client, ctx, OWNER)
    ctx.fakes["llm"].queue["post_plan"] += ["Sorry, here it is: {\"idea\": ", "{\"idea\": \"x\"}"]
    _, d = await generate(client, ctx, char=ch)
    assert d["status"] == "failed" and d["error"] == "llm_bad_json"
    assert "не удалось разобрать" in ctx.notifier.last(OWNER).text


async def test_broken_then_fixed_json(client, ctx):
    ch = await ready_character(client, ctx, OWNER)
    good = {"idea": "Sit-down", "slides": [{"scene": "the cat at a table"}], "caption": "Business.",
            "hashtags": ["cats", "#cat", "#Cat", "aicat", "#mafia", "#don", "#nyc"], "alt_text": "a cat", "summary": "s"}
    ctx.fakes["llm"].queue["post_plan"] += ["```json\n{\"idea\": \"x\",,}\n```", json.dumps(good)]
    _, d = await generate(client, ctx, char=ch)
    assert d["status"] == "pending_review" and len(d["slides"]) == 1
    assert d["hashtags"] == ["#cats", "#cat", "#aicat", "#mafia", "#don", "#nyc"]  # normalized, deduplicated


async def test_blocked_scene_needs_review(client, ctx):
    ch = await ready_character(client, ctx, OWNER)
    plan = {"idea": "Cap day", "slides": [{"scene": "the cat wearing a Nike cap"}], "caption": "c",
            "hashtags": ["#a", "#b", "#c", "#d", "#e"]}
    ctx.fakes["llm"].queue["post_plan"].append(json.dumps(plan))
    _, d = await generate(client, ctx, char=ch)
    assert d["status"] == "needs_review" and "nike" in d["slides"][0]["issues"][-1]


async def test_budget_stops_pipeline(client, ctx):
    await invite_user(client, 60)
    ch = await ready_character(client, ctx, 60)
    async with ctx.db.sessions() as s:
        from app.models import User
        (await s.get(User, 60)).budget_usd = 0.01
        await s.commit()
    _, d = await generate(client, ctx, uid=60, char=ch)
    assert d["status"] == "failed" and d["error"] == "budget_exceeded"
    texts = [m.text for m in ctx.notifier.sent if m.chat_id == 60]
    assert sum("Бюджет" in t for t in texts) == 1


async def test_drafts_api_is_private(client, ctx):
    await invite_user(client, 61)
    _, d = await generate(client, ctx)
    assert (await client.get(f"/api/drafts/{d['id']}", headers=auth(61))).status_code == 404
    assert (await client.get("/api/drafts", headers=auth(61))).json() == []
    assert len((await client.get("/api/drafts?status=pending_review", headers=auth(OWNER))).json()) == 1


async def test_settings_and_disclosure(client, ctx):
    ch = await ready_character(client, ctx, OWNER)
    r = await client.patch(f"/api/characters/{ch['id']}/settings", headers=auth(OWNER), json={
        "schedule": {"times": ["18:00", "25:00", "09:05"], "days": [0, 4, 9], "tz": "Europe/Berlin", "lead_hours": 8},
        "slides_max": 2, "ai_disclosure": False})
    assert r.json()["schedule"] == {"times": ["09:05", "18:00"], "days": [0, 4], "tz": "Europe/Berlin", "lead_hours": 8}
    r = await client.patch(f"/api/characters/{ch['id']}/settings", headers=auth(OWNER),
                           json={"schedule": {"times": [], "tz": "Mars/Base"}})
    assert r.status_code == 400
    _, d = await generate(client, ctx, char=ch)
    assert len(d["slides"]) == 2 and "AI character" not in d["final_caption"]


async def test_draft_message_escapes_html(ctx):
    ch = Character(name="<b>Don</b>", schedule={"tz": "UTC"}, ai_disclosure=True, disclosure_text="🤖 AI character")
    d = Draft(id=1, slot_ms=0, caption="1 < 2 & <script>", hashtags=["#a"], slides=[], qa_ok=True, rubric="")
    msg = draft_message(d, ch)
    assert "&lt;script&gt;" in msg and "&lt;b&gt;Don" in msg


def test_s3_storage_presigns(settings):
    from app.providers.storage import S3Storage, make_storage
    settings.s3_bucket, settings.s3_endpoint = "purr", "https://storage.example.com"
    settings.s3_access_key, settings.s3_secret_key = "AK", "SK"
    st = make_storage(settings)
    assert isinstance(st, S3Storage) and st.public
    url = st.url("u1/c1/d1/0.jpg")
    assert url.startswith("https://") and "X-Amz-Expires=3600" in url and "u1/c1/d1/0.jpg" in url
    settings.s3_public_base_url = "https://cdn.example.com"
    assert make_storage(settings).url("a b.jpg") == "https://cdn.example.com/a%20b.jpg"
