import json

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select, text

from app.config import Settings
from app.models import User
from app.providers import registry
from app.providers.base import ProviderError
from app.providers.fake import FakeImageGen, draw_cat
from app.providers.fal import FalClient, FalTrainer
from app.services import budget
from app.services.crypto import CryptoError, decrypt, encrypt

from .conftest import OWNER, auth, invite_user

# ---------- encryption ----------


def test_encrypt_roundtrip_and_wrong_key():
    s = Settings(encryption_key=Fernet.generate_key().decode())
    token = encrypt(s, "fal-secret-123")
    assert "fal-secret-123" not in token and decrypt(s, token) == "fal-secret-123"
    other = Settings(encryption_key=Fernet.generate_key().decode())
    with pytest.raises(CryptoError):
        decrypt(other, token)


def test_no_key_in_production():
    with pytest.raises(CryptoError):
        encrypt(Settings(encryption_key="", dev_auth=False, dev_fake_providers=False), "x")
    with pytest.raises(CryptoError):
        encrypt(Settings(encryption_key="not-a-fernet-key"), "x")


async def test_own_keys_stored_encrypted_never_returned(client, app):
    await invite_user(client, 7)
    r = await client.put("/api/me/keys", json={"fal": "fal-key-abcdef123456", "anthropic": "sk-ant-api03-zzzzzz9999"},
                         headers=auth(7))
    assert r.json() == {"fal": "fal-…3456", "anthropic": "sk-a…9999"}
    async with app.state.db.sessions() as s:
        raw = (await s.execute(text("select fal_key_enc, anthropic_key_enc from users where id = 7"))).one()
    assert "fal-key-abcdef123456" not in raw[0] and "sk-ant" not in raw[1]
    me = (await client.get("/api/me", headers=auth(7))).text
    assert "abcdef" not in me and "sk-ant" not in me
    assert json.loads(me)["own_keys"] == {"fal": True, "anthropic": True}
    r = await client.put("/api/me/keys", json={"fal": ""}, headers=auth(7))
    assert r.json()["fal"] is None and r.json()["anthropic"]


# ---------- budget ----------


async def _user(s, uid=7, budget_usd=1.0):
    u = User(id=uid, is_active=True, budget_usd=budget_usd)
    s.add(u)
    await s.flush()
    return u


async def test_budget_stops_generation_and_notifies_once(ctx):
    p = registry.for_user(ctx, None)
    async with ctx.db.sessions() as s:
        u = await _user(s)
        await budget.ensure(s, ctx, u, p)  # nothing spent yet
        for _ in range(30):  # 30 candidates x $0.025 = $0.75
            res = await p.images.generate("ginger cat", 1, 1024, 1024)
            budget.record(s, u.id, res.usage)
        await s.commit()
        await budget.ensure(s, ctx, u, p)
        res = await p.images.generate("ginger cat", 12, 1024, 1024)  # +$0.30 -> over $1
        budget.record(s, u.id, res.usage)
        await s.commit()
        with pytest.raises(budget.BudgetExceeded):
            await budget.ensure(s, ctx, u, p)
        with pytest.raises(budget.BudgetExceeded):
            await budget.ensure(s, ctx, u, p)
    msgs = [m for m in ctx.notifier.sent if m.chat_id == 7]
    assert len(msgs) == 1 and "Бюджет" in msgs[0].text


async def test_own_keys_bypass_shared_budget(ctx):
    async with ctx.db.sessions() as s:
        u = await _user(s, budget_usd=0)
        p = registry.for_user(ctx, u)
        with pytest.raises(budget.BudgetExceeded):
            await budget.ensure(s, ctx, u, p)
        own = registry.Providers(*(type(x)(billed_to="own") for x in (p.llm, p.images, p.trainer)))
        await budget.ensure(s, ctx, u, own)  # no exception
        res = await own.images.generate("cat", 2, 1024, 1024)
        budget.record(s, u.id, res.usage)
        await s.commit()
        assert await budget.spent(s, u.id, ctx.settings) == 0
        assert await budget.spent(s, u.id, ctx.settings, "own") > 0


async def test_budget_is_per_user_and_monthly(ctx):
    async with ctx.db.sessions() as s:
        a, b = await _user(s, 7), await _user(s, 8)
        res = await FakeImageGen().generate("cat", 4, 1024, 1024)
        budget.record(s, a.id, res.usage)
        old = budget.record(s, b.id, res.usage)
        await s.commit()
        old.created_ms = budget.month_start_ms(ctx.settings) - 1  # last month
        await s.commit()
        assert await budget.spent(s, a.id, ctx.settings) == pytest.approx(0.1049)
        assert await budget.spent(s, b.id, ctx.settings) == 0


async def test_me_and_admin_show_spend(client, ctx):
    await invite_user(client, 9)
    async with ctx.db.sessions() as s:
        budget.record(s, 9, (await FakeImageGen().generate("cat", 4, 1024, 1024)).usage)
        await s.commit()
    me = (await client.get("/api/me", headers=auth(9))).json()
    assert me["budget"]["spent"] == 0.1 and me["budget"]["limit"] == 15
    users = (await client.get("/api/admin/users", headers=auth(OWNER))).json()
    assert next(u for u in users if u["id"] == 9)["spent_usd"] == 0.1


async def test_missing_keys_fail_clearly(ctx):
    ctx.settings.dev_fake_providers = False
    p = registry.for_user(ctx, None)
    with pytest.raises(ProviderError) as e:
        await p.images.generate("cat", 1, 512, 512)
    assert e.value.code == "fal_not_configured"


# ---------- fake images and local media ----------


async def test_fake_images_are_jpegs_and_served_signed(client, ctx):
    data = draw_cat("ginger tabby cat in a fedora", 270, 338)
    assert data[:3] == b"\xff\xd8\xff"
    await ctx.storage.put("t/cat.jpg", data, "image/jpeg")
    url = ctx.storage.url("t/cat.jpg")
    assert (await client.get(url)).content == data
    assert (await client.get(url.replace("sig=", "sig=0"))).status_code == 403


# ---------- fal.ai client against a mocked HTTP API ----------


def fal_mock(state: dict):
    def handler(req: httpx.Request) -> httpx.Response:
        u = str(req.url)
        if "fal.run" in u or u.startswith("https://q/"):
            assert req.headers["authorization"] == "Key k"
        if req.method == "POST" and u.startswith("https://queue.fal.run/"):
            state["payloads"].append(json.loads(req.content))
            return httpx.Response(200, json={"request_id": "r1", "status_url": "https://q/s", "response_url": "https://q/r"})
        if u == "https://q/s":
            state["polls"] += 1
            return httpx.Response(200, json={"status": "COMPLETED" if state["polls"] > 1 else "IN_PROGRESS"})
        if u == "https://q/r":
            return httpx.Response(200, json=state["result"])
        if u.startswith("https://img/"):
            return httpx.Response(200, content=b"JPEG" + u.encode())
        return httpx.Response(404)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_fal_generate_polls_and_downloads():
    st = {"payloads": [], "polls": 0, "result": {"images": [{"url": "https://img/1"}, {"url": "https://img/2"}]}}
    fal = FalClient(Settings(), "k", http=fal_mock(st), poll_every=0)
    res = await fal.generate_lora("PRP_don cat", "https://w/lora.safetensors", 2, 1080, 1350, seed=5)
    assert res.images == [b"JPEGhttps://img/1", b"JPEGhttps://img/2"]
    assert st["payloads"][0]["loras"] == [{"path": "https://w/lora.safetensors", "scale": 1.0}]
    assert st["payloads"][0]["image_size"] == {"width": 1080, "height": 1350}
    assert res.usage.cost_usd == pytest.approx(0.035 * 1.458 * 2, rel=1e-3)


async def test_fal_training_status():
    st = {"payloads": [], "polls": 5, "result": {"diffusers_lora_file": {"url": "https://w/x.safetensors"}}}
    tr = FalTrainer(FalClient(Settings(), "k", http=fal_mock(st), poll_every=0))
    handle, usage = await tr.submit("https://zip", "PRP_don")
    assert st["payloads"][0]["trigger_word"] == "PRP_don" and usage.cost_usd == 2.0
    status = await tr.status(handle)
    assert status.state == "done" and status.lora_url == "https://w/x.safetensors"


async def test_fal_errors_mapped():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(401, json={})))
    with pytest.raises(ProviderError) as e:
        await FalClient(Settings(), "k", http=client).generate("cat", 1, 512, 512)
    assert e.value.code == "fal_auth"
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    with pytest.raises(ProviderError) as e:
        await FalClient(Settings(), "k", http=client).generate("cat", 1, 512, 512)
    assert e.value.retryable


async def test_users_table(ctx):
    async with ctx.db.sessions() as s:
        assert (await s.execute(select(User))).scalars().all() == []


# ---------- Anthropic client against a mocked HTTP API ----------


def anthropic_mock(stop_reason="end_turn", text_out='{"ok": true}'):
    import anthropic
    import httpx2

    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        seen["beta"] = req.headers.get("anthropic-beta")
        return httpx2.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": [{"type": "text", "text": text_out}], "stop_reason": stop_reason, "stop_sequence": None,
            "usage": {"input_tokens": 1000, "output_tokens": 500}})

    return anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler)), seen


async def test_anthropic_request_shape_and_cost():
    from app.providers.anthropic_llm import AnthropicLLM

    http, seen = anthropic_mock()
    llm = AnthropicLLM(Settings(anthropic_model="claude-opus-5-5"), "k", http_client=http)
    img = {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "AAAA"}}
    res = await llm.complete("qa", "system text", [img, {"type": "text", "text": "check"}])
    assert res.text == '{"ok": true}'
    assert res.usage.cost_usd == pytest.approx(1000 / 1e6 * 4 + 500 / 1e6 * 20)
    assert seen["body"]["output_config"] == {"effort": "medium"} and seen["body"]["fallbacks"] == "default"
    assert seen["body"]["system"] == "system text" and seen["body"]["messages"][0]["content"][0] == img
    assert "server-side-fallback-2026-07-01" in seen["beta"]


async def test_anthropic_refusal():
    from app.providers.anthropic_llm import AnthropicLLM

    http, _ = anthropic_mock(stop_reason="refusal", text_out="")
    with pytest.raises(ProviderError) as e:
        await AnthropicLLM(Settings(), "k", http_client=http).complete("qa", "s", [{"type": "text", "text": "x"}])
    assert e.value.code == "llm_refused"
