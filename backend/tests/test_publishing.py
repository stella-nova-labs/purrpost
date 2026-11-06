import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy import func, select, text

from app.config import Settings
from app.models import Account, Draft, Publication
from app.publishers.base import Creds, Media, Post, PublishError
from app.publishers.instagram import InstagramPublisher
from app.publishers.threads import ThreadsPublisher, threads_text
from app.services import oauth, publishing
from app.services.approval import handle_callback

from .conftest import OWNER, auth, invite_user, ready_character, run_jobs
from .test_pipeline import generate


async def connect(client, cid, platform="instagram", uid=OWNER):
    r = await client.get(f"/api/oauth/{platform}/start?character_id={cid}", headers=auth(uid))
    url = urlparse(r.json()["url"])
    r = await client.get(f"{url.path}?{url.query}")
    assert r.status_code == 200, r.text
    return r


async def approved_due(client, ctx, platforms=("instagram",), uid=OWNER, ch=None):
    ch = ch or await ready_character(client, ctx, uid)
    for p in platforms:
        if p == "telegram":
            await client.post(f"/api/characters/{ch['id']}/accounts/telegram", json={"channel": "@donchannel"},
                              headers=auth(uid))
        else:
            await connect(client, ch["id"], p, uid)
    _, d = await generate(client, ctx, uid=uid, char=ch)
    await handle_callback(ctx, uid, f"d:ok:{d['id']}")
    async with ctx.db.sessions() as s:
        (await s.get(Draft, d["id"])).slot_ms = 0  # time has come
        await s.commit()
    return ch, d


async def test_oauth_connect_stores_encrypted_token(client, ctx):
    ch = await ready_character(client, ctx, OWNER)
    r = await connect(client, ch["id"])
    assert "Instagram подключён" in r.text
    accs = (await client.get(f"/api/characters/{ch['id']}/accounts", headers=auth(OWNER))).json()
    assert accs[0]["platform"] == "instagram" and accs[0]["username"] == "fake_instagram"
    assert "token" not in json.dumps(accs).replace("token_expires_ms", "")
    async with ctx.db.sessions() as s:
        raw = (await s.execute(text("select token_enc from accounts"))).scalar_one()
    assert "fake-token" not in raw


async def test_oauth_state_is_checked(client, ctx):
    ch = await ready_character(client, ctx, OWNER)
    good = oauth.sign_state(ctx.settings, OWNER, ch["id"], "instagram")
    r = await client.get(f"/api/oauth/instagram/callback?code=x&state={good[:-2]}xx")
    assert r.status_code == 400 and "повреждена" in r.text
    other = oauth.sign_state(ctx.settings, 999, ch["id"], "instagram")  # not the owner of the character
    assert (await client.get(f"/api/oauth/instagram/callback?code=x&state={other}")).status_code == 400
    old = oauth.sign_state(ctx.settings, OWNER, ch["id"], "instagram", now=1)
    assert "устарела" in (await client.get(f"/api/oauth/instagram/callback?code=x&state={old}")).text
    r = await client.get(f"/api/oauth/instagram/callback?error=access_denied&state={good}")
    assert "отменили" in r.text


async def test_publish_flow_and_idempotency(client, ctx):
    ch, d = await approved_due(client, ctx, ("instagram", "telegram"))
    await run_jobs(ctx)
    await run_jobs(ctx)  # again: nothing new
    assert await publishing.start_due(ctx) == 0
    ig, tg = ctx.publishers["instagram"], ctx.publishers["telegram"]
    assert len(ig.posts) == 1 and len(tg.posts) == 1
    post = ig.posts[0][1]
    assert len(post.media) == 3 and post.caption.endswith("🤖 AI character") and "#aicat" in post.caption
    d2 = (await client.get(f"/api/drafts/{d['id']}", headers=auth(OWNER))).json()
    assert d2["status"] == "published" and d2["published_ms"]
    async with ctx.db.sessions() as s:
        assert (await s.execute(select(func.count()).select_from(Publication))).scalar_one() == 2
    c = (await client.get(f"/api/characters/{ch['id']}", headers=auth(OWNER))).json()
    assert c["lore"][-1]["summary"]  # remembered for future posts
    msg = ctx.notifier.last(OWNER)
    assert "пост опубликован" in msg.text and "https://example.com/instagram/instagram-1" in msg.text


async def test_unique_publication_per_platform(client, ctx):
    _, d = await approved_due(client, ctx)
    assert await publishing.start_due(ctx) == 1
    async with ctx.db.sessions() as s:  # simulate the draft flipping back by a bug/race
        (await s.get(Draft, d["id"])).status = "scheduled"
        await s.commit()
    await publishing.start_due(ctx)
    async with ctx.db.sessions() as s:
        assert (await s.execute(select(func.count()).select_from(Publication))).scalar_one() == 1


async def test_retry_resumes_without_duplicate(client, ctx):
    """A crash after the platform published (media id saved in state) must not post again."""
    _, d = await approved_due(client, ctx)
    await publishing.start_due(ctx)
    async with ctx.db.sessions() as s:
        p = (await s.execute(select(Publication))).scalar_one()
        p.state = {"media_id": "instagram-77"}
        await s.commit()
    await publishing.process(ctx)
    assert ctx.publishers["instagram"].posts == []
    async with ctx.db.sessions() as s:
        p = (await s.execute(select(Publication))).scalar_one()
    assert p.status == "published" and p.external_id == "instagram-77"


async def test_retries_with_backoff_then_success(client, ctx):
    _, d = await approved_due(client, ctx)
    ig = ctx.publishers["instagram"]
    ig.fail_with += [PublishError("platform_unavailable", "503", retryable=True)] * 2
    delays = []
    for _ in range(3):
        await run_jobs(ctx, 1)
        async with ctx.db.sessions() as s:
            p = (await s.execute(select(Publication))).scalar_one()
            if p.status == "retry":
                delays.append(p.next_attempt_ms - p.claimed_ms)
                p.next_attempt_ms = 0  # fast-forward
                await s.commit()
    assert p.status == "published" and p.attempts == 3
    assert [round(x / 60_000) for x in delays] == [1, 2]


async def test_gives_up_after_max_attempts(client, ctx):
    _, d = await approved_due(client, ctx)
    ctx.publishers["instagram"].fail_with += [PublishError("platform_unavailable", retryable=True)] * 10
    for _ in range(6):
        await run_jobs(ctx, 1)
        async with ctx.db.sessions() as s:
            await s.execute(text("update publications set next_attempt_ms = 0"))
            await s.commit()
    async with ctx.db.sessions() as s:
        p = (await s.execute(select(Publication))).scalar_one()
    assert p.status == "failed" and p.attempts == publishing.MAX_ATTEMPTS
    assert (await client.get(f"/api/drafts/{d['id']}", headers=auth(OWNER))).json()["status"] == "failed"
    assert "Instagram не отвечает" in ctx.notifier.last(OWNER).text


async def test_token_expired_is_clear(client, ctx):
    ch, d = await approved_due(client, ctx, ("instagram", "telegram"))
    ctx.publishers["instagram"].fail_with.append(PublishError("token_expired", "Error validating access token",
                                                              account_broken=True))
    await run_jobs(ctx)
    d2 = (await client.get(f"/api/drafts/{d['id']}", headers=auth(OWNER))).json()
    assert d2["status"] == "partially_published"
    accs = (await client.get(f"/api/characters/{ch['id']}/accounts", headers=auth(OWNER))).json()
    assert next(a for a in accs if a["platform"] == "instagram")["status"] == "expired"
    assert "токен истёк — переподключите Instagram" in ctx.notifier.last(OWNER).text


async def test_no_accounts(client, ctx):
    _, d = await approved_due(client, ctx, ())
    await run_jobs(ctx)
    d2 = (await client.get(f"/api/drafts/{d['id']}", headers=auth(OWNER))).json()
    assert d2["status"] == "failed" and d2["error"] == "no_accounts"
    assert "нет подключённых соцсетей" in ctx.notifier.last(OWNER).text


async def test_autopilot_post_can_be_deleted(client, ctx):
    ch = await ready_character(client, ctx, OWNER)
    async with ctx.db.sessions() as s:
        from app.models import Character
        (await s.get(Character, ch["id"])).autopilot = True
        await s.commit()
    await connect(client, ch["id"])
    _, d = await generate(client, ctx, char=ch)
    assert d["status"] == "scheduled"
    async with ctx.db.sessions() as s:
        (await s.get(Draft, d["id"])).slot_ms = 0
        await s.commit()
    await run_jobs(ctx)
    msg = ctx.notifier.last(OWNER)
    assert "автопилот" in msg.text and msg.photos == 3 and msg.buttons[0][0].data == f"p:del:{d['id']}"
    assert await publishing.handle_callback(ctx, 5, f"p:del:{d['id']}") == "Пост не найден"
    assert await publishing.handle_callback(ctx, OWNER, f"p:del:{d['id']}") == "🗑 Пост удалён"
    assert ctx.publishers["instagram"].deleted == ["instagram-1"]
    assert await publishing.handle_callback(ctx, OWNER, f"p:del:{d['id']}") == "Пост уже удалён"


async def test_accounts_are_private(client, ctx):
    await invite_user(client, 90)
    ch = await ready_character(client, ctx, OWNER)
    await connect(client, ch["id"])
    assert (await client.get(f"/api/characters/{ch['id']}/accounts", headers=auth(90))).status_code == 404
    assert (await client.get(f"/api/oauth/instagram/start?character_id={ch['id']}", headers=auth(90))).status_code == 404
    aid = (await client.get(f"/api/characters/{ch['id']}/accounts", headers=auth(OWNER))).json()[0]["id"]
    assert (await client.delete(f"/api/accounts/{aid}", headers=auth(90))).status_code == 404


# ---------- Instagram Graph API with mocked HTTP ----------

class GraphMock:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        body = parse_qs(req.content.decode()) if req.content else {}
        params = {k: v[0] for k, v in {**parse_qs(req.url.query.decode()), **body}.items()}
        path = req.url.path.split("/", 2)[-1]
        self.calls.append((req.method, path, params))
        for (method, prefix), handler in self.routes.items():
            if req.method == method and path.startswith(prefix):
                res = handler(params) if callable(handler) else handler
                return res if isinstance(res, httpx.Response) else httpx.Response(200, json=res)
        return httpx.Response(404, json={"error": {"message": f"no route {req.method} {path}", "code": 100}})


def ig(routes):
    mock = GraphMock(routes)
    pub = InstagramPublisher(Settings(), httpx.AsyncClient(transport=httpx.MockTransport(mock)), poll_every=0)
    return pub, mock


CREDS = Creds("1784", "tok")
LIMIT_OK = {"data": [{"quota_usage": 3, "config": {"quota_total": 100}}]}


async def test_instagram_carousel_flow():
    n = {"i": 0}

    def child(p):
        n["i"] += 1
        assert p["is_carousel_item"] == "true" and p["image_url"].startswith("https://s3/")
        return {"id": f"c{n['i']}"}

    pub, mock = ig({
        ("GET", "1784/content_publishing_limit"): LIMIT_OK,
        ("POST", "1784/media_publish"): lambda p: {"id": "M1"} if p["creation_id"] == "CAR" else {},
        ("POST", "1784/media"): lambda p: {"id": "CAR"} if p.get("media_type") == "CAROUSEL" else child(p),
        ("GET", "c"): {"status_code": "FINISHED"},
        ("GET", "CAR"): {"status_code": "FINISHED"},
        ("GET", "M1"): {"permalink": "https://instagram.com/p/abc"},
    })
    state: dict = {}
    res = await pub.publish(CREDS, Post([Media(f"https://s3/{i}.jpg") for i in range(3)], "Hi #cat", "alt"), state)
    assert res.external_id == "M1" and res.permalink == "https://instagram.com/p/abc"
    car = next(c for c in mock.calls if c[2].get("media_type") == "CAROUSEL")
    assert car[2]["children"] == "c1,c2,c3" and car[2]["caption"] == "Hi #cat" and car[2]["access_token"] == "tok"
    assert state == {"children": ["c1", "c2", "c3"], "container": "CAR", "media_id": "M1"}
    # resume after a crash between container and publish: no new containers
    mock.calls.clear()
    res = await pub.publish(CREDS, Post([Media("x")], "Hi"), {"container": "CAR"})
    assert res.external_id == "M1" and not any(c[1] == "1784/media" for c in mock.calls)


async def test_instagram_single_photo_and_limit():
    pub, mock = ig({
        ("GET", "1784/content_publishing_limit"): LIMIT_OK,
        ("POST", "1784/media_publish"): {"id": "M2"},
        ("POST", "1784/media"): {"id": "ONE"},
        ("GET", "ONE"): {"status_code": "FINISHED"},
        ("GET", "M2"): {"permalink": "p"},
    })
    await pub.publish(CREDS, Post([Media("https://s3/1.jpg")], "cap", "a cat"), {})
    single = next(c for c in mock.calls if c[1] == "1784/media")
    assert single[2]["image_url"] == "https://s3/1.jpg" and single[2]["caption"] == "cap" and single[2]["alt_text"] == "a cat"

    pub, _ = ig({("GET", "1784/content_publishing_limit"): {"data": [{"quota_usage": 100, "config": {"quota_total": 100}}]}})
    with pytest.raises(PublishError) as e:
        await pub.publish(CREDS, Post([Media("u")], "c"), {})
    assert e.value.code == "publish_limit" and e.value.retryable and e.value.retry_after_ms


@pytest.mark.parametrize("err,code,retryable", [
    ({"code": 190, "message": "Error validating access token"}, "token_expired", False),
    ({"code": 9, "error_subcode": 2207042, "message": "limit"}, "publish_limit", True),
    ({"code": 4, "message": "Application request limit reached"}, "rate_limited", True),
    ({"code": 10, "message": "no permission"}, "permission_denied", False),
    ({"code": 1, "error_subcode": 2207052, "message": "media fetch"}, "media_fetch_failed", True),
    ({"code": 100, "message": "Invalid parameter"}, "platform_error", False),
])
async def test_instagram_error_mapping(err, code, retryable):
    pub, _ = ig({("GET", "1784/content_publishing_limit"): httpx.Response(400, json={"error": err})})
    with pytest.raises(PublishError) as e:
        await pub.publish(CREDS, Post([Media("u")], "c"), {})
    assert (e.value.code, e.value.retryable) == (code, retryable)


async def test_instagram_container_error_starts_over():
    pub, _ = ig({("GET", "1784/content_publishing_limit"): LIMIT_OK, ("POST", "1784/media"): {"id": "BAD"},
                 ("GET", "BAD"): {"status_code": "ERROR"}})
    state: dict = {}
    with pytest.raises(PublishError) as e:
        await pub.publish(CREDS, Post([Media("u")], "c"), state)
    assert e.value.code == "media_rejected" and e.value.retryable and state == {}


async def test_instagram_metrics():
    pub, _ = ig({("GET", "M1/insights"): {"data": [{"name": "reach", "values": [{"value": 1200}]},
                                                  {"name": "saved", "values": [{"value": 30}]}]},
                 ("GET", "M1"): {"like_count": 140, "comments_count": 12}})
    assert await pub.metrics(CREDS, "M1") == {"likes": 140, "comments": 12, "reach": 1200, "saves": 30}


async def test_threads_text_and_flow():
    caption = "Short story.\n\n#a #b #c\n\n🤖 AI character"
    assert threads_text(caption) == "Short story.\n\n🤖 AI character"
    assert len(threads_text("x" * 900)) == 500
    mock = GraphMock({("POST", "99/threads_publish"): {"id": "T1"}, ("POST", "99/threads"): {"id": "TC"},
                      ("GET", "TC"): {"status": "FINISHED"}, ("GET", "T1"): {"permalink": "https://threads.net/t/1"}})
    pub = ThreadsPublisher(httpx.AsyncClient(transport=httpx.MockTransport(mock)), poll_every=0)
    res = await pub.publish(Creds("99", "tok"), Post([Media("https://s3/1.jpg")], caption), {})
    assert res.permalink == "https://threads.net/t/1"
    assert mock.calls[0][2]["text"] == "Short story.\n\n🤖 AI character" and mock.calls[0][2]["media_type"] == "IMAGE"


# ---------- OAuth exchange and refresh with mocked HTTP ----------

def oauth_http(short=None, long=None, me=None, status=200):
    def handler(req):
        u = str(req.url)
        if "api.instagram.com/oauth/access_token" in u:
            return httpx.Response(status, json=short)
        if "graph.instagram.com/access_token" in u:
            return httpx.Response(200, json=long)
        if "/me" in u:
            return httpx.Response(200, json=me)
        return httpx.Response(404)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_instagram_exchange():
    s = Settings(meta_app_id="app", meta_app_secret="sec", webapp_url="https://pp.example")
    http = oauth_http({"data": [{"access_token": "short", "user_id": "17", "permissions": "x"}]},
                      {"access_token": "long", "expires_in": 5184000}, {"user_id": "1784", "username": "don.whiskers",
                                                                         "account_type": "BUSINESS"})
    tok = await oauth.exchange(s, http, "instagram", "code", 1000)
    assert (tok.access_token, tok.user_id, tok.username) == ("long", "1784", "don.whiskers")
    assert tok.expires_ms == 1000 + 5184000 * 1000
    url = oauth.authorize_url(s, "instagram", "st")
    q = parse_qs(urlparse(url).query)
    assert q["redirect_uri"] == ["https://pp.example/api/oauth/instagram/callback"]
    assert "instagram_business_content_publish" in q["scope"][0]


async def test_instagram_exchange_errors():
    s = Settings(meta_app_id="app", meta_app_secret="sec")
    http = oauth_http({"error_type": "OAuthException", "code": 400,
                       "error_message": "Insufficient developer role"}, status=400)
    with pytest.raises(oauth.OAuthError) as e:
        await oauth.exchange(s, http, "instagram", "code", 0)
    assert e.value.code == "not_tester"
    http = oauth_http({"access_token": "s", "user_id": "1"}, {"access_token": "l", "expires_in": 10},
                      {"user_id": "1", "username": "x", "account_type": "PERSONAL"})
    with pytest.raises(oauth.OAuthError) as e:
        await oauth.exchange(s, http, "instagram", "code", 0)
    assert e.value.code == "not_business"


async def test_callback_shows_tester_hint(client, ctx, monkeypatch):
    ch = await ready_character(client, ctx, OWNER)

    async def boom(*a, **kw):
        raise oauth.OAuthError("not_tester", "Insufficient developer role")

    monkeypatch.setattr(oauth, "exchange", boom)
    st = oauth.sign_state(ctx.settings, OWNER, ch["id"], "instagram")
    r = await client.get(f"/api/oauth/instagram/callback?code=x&state={st}")
    assert r.status_code == 400 and "Instagram Testers" in r.text and "Приглашения тестировщика" in r.text


async def test_refresh_tokens(client, ctx, monkeypatch):
    ch = await ready_character(client, ctx, OWNER)
    await connect(client, ch["id"])
    await connect(client, ch["id"], "threads")
    async with ctx.db.sessions() as s:
        await s.execute(text("update accounts set token_expires_ms = 1, token_refreshed_ms = null"))
        await s.commit()
    assert await publishing.refresh_tokens(ctx) == 2
    assert await publishing.refresh_tokens(ctx) == 0  # refreshed: far from expiry now

    async def expired(*a, **kw):
        raise PublishError("token_expired", "190")

    monkeypatch.setattr(oauth, "refresh", expired)
    async with ctx.db.sessions() as s:
        await s.execute(text("update accounts set token_expires_ms = 1, token_refreshed_ms = null"))
        await s.commit()
    await publishing.refresh_tokens(ctx)
    async with ctx.db.sessions() as s:
        assert {a.status for a in (await s.execute(select(Account))).scalars()} == {"expired"}
    assert "истёк" in ctx.notifier.last(OWNER).text


# ---------- Telegram channel with a recording Bot API session ----------

async def test_telegram_channel_publisher():
    from aiogram import Bot
    from aiogram.methods import SendMediaGroup, SendMessage

    from app.publishers.telegram import TelegramChannelPublisher

    from .test_bot import RecordingSession

    class Session(RecordingSession):
        async def make_request(self, bot, method, timeout=None):
            if isinstance(method, SendMediaGroup):
                self.calls.append(method)
                from aiogram.types import Chat, Message
                return [Message(message_id=40 + i, date=0, chat=Chat(id=-100, type="channel")) for i in range(len(method.media))]
            return await super().make_request(bot, method, timeout)

    session = Session()
    pub = TelegramChannelPublisher(Bot("123456:TEST-TOKEN", session=session))
    state: dict = {}
    res = await pub.publish(Creds("-100", None, "donchannel"), Post([Media("", b"a"), Media("", b"b")], "Caption"), state)
    group = session.calls[0]
    assert isinstance(group, SendMediaGroup) and group.media[0].caption == "Caption" and group.media[1].caption is None
    assert res.permalink == "https://t.me/donchannel/40" and state["message_ids"] == [40, 41]
    session.calls.clear()
    await pub.publish(Creds("-100", None, ""), Post([Media("", b"a"), Media("", b"b")], "x" * 1500), {})
    assert session.calls[0].media[0].caption is None and isinstance(session.calls[1], SendMessage)
