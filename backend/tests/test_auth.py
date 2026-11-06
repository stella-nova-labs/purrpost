import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest

from app.telegram_auth import AuthError, parse_invite, validate_init_data

from .conftest import BOT_TOKEN, OWNER, auth, invite_user


def sign(data: dict, token: str = BOT_TOKEN) -> str:
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    return urlencode({**data, "hash": hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()})


def init_data(uid: int = 42, age: int = 0, **extra) -> str:
    return sign({"auth_date": str(int(time.time()) - age), "user": json.dumps({"id": uid, "first_name": "A"}),
                 **extra})


def test_valid_signature():
    u = validate_init_data(init_data(7, start_param="inv_ABC123"), BOT_TOKEN, 86400)
    assert u.id == 7 and u.start_param == "inv_ABC123"


def test_bad_signature_and_expired():
    with pytest.raises(AuthError):
        validate_init_data(init_data().replace("hash=", "hash=0"), BOT_TOKEN, 86400)
    with pytest.raises(AuthError):
        validate_init_data(init_data(age=90000), BOT_TOKEN, 86400)
    with pytest.raises(AuthError):
        validate_init_data(init_data(), "999:OTHER", 86400)


def test_parse_invite():
    assert parse_invite("inv_abc123") == "ABC123"
    assert parse_invite("ref_1") is None and parse_invite(None) is None


async def test_real_init_data_accepted(client):
    r = await client.get("/api/me", headers={"Authorization": f"tma {init_data(OWNER)}"})
    assert r.status_code == 200 and r.json()["user"]["is_owner"]


async def test_no_auth(client):
    assert (await client.get("/api/me")).status_code == 401
    assert (await client.get("/api/me", headers={"Authorization": "tma garbage"})).status_code == 401


async def test_dev_auth_disabled(app, client, settings):
    settings.dev_auth = False
    assert (await client.get("/api/me", headers=auth(OWNER))).status_code == 401


async def test_owner_active_stranger_needs_invite(client):
    r = await client.get("/api/me", headers=auth(OWNER))
    assert r.json()["user"]["is_active"] and r.json()["user"]["is_admin"]
    r = await client.get("/api/me", headers=auth(5))
    assert r.json()["user"]["is_active"] is False
    assert (await client.get("/api/admin/invites", headers=auth(5))).status_code == 403


async def test_invite_limit(client):
    r = await client.post("/api/admin/invites", json={"max_uses": 2, "note": "friends"}, headers=auth(OWNER))
    code = r.json()["code"]
    assert r.json()["link"] == f"https://t.me/purrpost_test_bot?start=inv_{code}"
    for uid in (10, 11):
        r = await client.post("/api/invite/redeem", json={"code": code.lower()}, headers=auth(uid))
        assert r.status_code == 200 and r.json()["user"]["is_active"]
    r = await client.post("/api/invite/redeem", json={"code": code}, headers=auth(12))
    assert r.status_code == 400 and r.json()["detail"] == "invite_exhausted"
    r = await client.post("/api/invite/redeem", json={"code": "NOPE1234"}, headers=auth(12))
    assert r.json()["detail"] == "invite_not_found"
    # redeeming again by an active user doesn't spend a use
    r = await client.post("/api/invite/redeem", json={"code": code}, headers=auth(10))
    assert r.status_code == 200
    invites = (await client.get("/api/admin/invites", headers=auth(OWNER))).json()
    assert invites[0]["uses"] == 2


async def test_start_param_redeems(client):
    r = await client.post("/api/admin/invites", json={}, headers=auth(OWNER))
    code = r.json()["code"]
    r = await client.get("/api/me", headers=auth(20, f"inv_{code}"))
    assert r.json()["user"]["is_active"]


async def test_disabled_invite(client):
    code = (await client.post("/api/admin/invites", json={}, headers=auth(OWNER))).json()["code"]
    await client.delete(f"/api/admin/invites/{code}", headers=auth(OWNER))
    r = await client.post("/api/invite/redeem", json={"code": code}, headers=auth(30))
    assert r.json()["detail"] == "invite_not_found"


async def test_admin_budget_and_users(client):
    await invite_user(client, 40)
    r = await client.patch("/api/admin/users/40", json={"budget_usd": 25}, headers=auth(OWNER))
    assert r.status_code == 200
    users = (await client.get("/api/admin/users", headers=auth(OWNER))).json()
    assert next(u for u in users if u["id"] == 40)["budget_usd"] == 25
    assert (await client.patch("/api/admin/users/40", json={"budget_usd": 1}, headers=auth(40))).status_code == 403
