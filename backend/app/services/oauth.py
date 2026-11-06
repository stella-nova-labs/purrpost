"""OAuth for Instagram (Instagram API with Instagram Login) and Threads, long-lived tokens and their refresh."""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from ..config import Settings
from ..publishers.base import PublishError
from ..publishers.graph import graph_error

IG_SCOPES = "instagram_business_basic,instagram_business_content_publish,instagram_business_manage_insights"
TH_SCOPES = "threads_basic,threads_content_publish,threads_manage_insights"
STATE_TTL = 30 * 60


class OAuthError(Exception):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code, self.message = code, message or code


@dataclass
class Token:
    access_token: str
    expires_ms: int | None
    user_id: str = ""
    username: str = ""
    account_type: str = ""


def _secret(s: Settings) -> bytes:
    return (s.encryption_key or s.bot_token or "purrpost-dev").encode()


def sign_state(s: Settings, user_id: int, character_id: int, platform: str, now: float | None = None) -> str:
    exp = int((now or time.time()) + STATE_TTL)
    body = f"{user_id}.{character_id}.{platform}.{exp}"
    return body + "." + hmac.new(_secret(s), body.encode(), hashlib.sha256).hexdigest()[:24]


def read_state(s: Settings, state: str, now: float | None = None) -> tuple[int, int, str]:
    try:
        uid, cid, platform, exp, sig = state.split(".")
    except ValueError as e:
        raise OAuthError("bad_state") from e
    body = f"{uid}.{cid}.{platform}.{exp}"
    if not hmac.compare_digest(sig, hmac.new(_secret(s), body.encode(), hashlib.sha256).hexdigest()[:24]):
        raise OAuthError("bad_state")
    if int(exp) < (now or time.time()):
        raise OAuthError("state_expired")
    return int(uid), int(cid), platform


def redirect_uri(s: Settings, platform: str) -> str:
    return f"{s.base_url}/api/oauth/{platform}/callback"


def authorize_url(s: Settings, platform: str, state: str) -> str:
    if s.dev_fake_providers:
        return f"{redirect_uri(s, platform)}?{urlencode({'code': 'fake', 'state': state})}"
    if platform == "instagram":
        if not s.meta_app_id:
            raise OAuthError("meta_not_configured")
        return "https://www.instagram.com/oauth/authorize?" + urlencode({
            "client_id": s.meta_app_id, "redirect_uri": redirect_uri(s, platform), "response_type": "code",
            "scope": IG_SCOPES, "state": state, "enable_fb_login": "0", "force_authentication": "1"})
    if platform == "threads":
        if not s.threads_app_id:
            raise OAuthError("threads_not_configured")
        return "https://threads.net/oauth/authorize?" + urlencode({
            "client_id": s.threads_app_id, "redirect_uri": redirect_uri(s, platform), "response_type": "code",
            "scope": TH_SCOPES, "state": state})
    raise OAuthError("bad_platform")


def _oauth_error(r: httpx.Response) -> OAuthError:
    try:
        j = r.json()
    except ValueError:
        j = {}
    err = j.get("error")
    if isinstance(err, dict):
        msg = err.get("message")
    else:
        msg = j.get("error_message") or j.get("error_description") or (err if isinstance(err, str) else None)
    msg = str(msg or f"HTTP {r.status_code}")
    low = msg.lower()
    if any(w in low for w in ("tester", "not authorized", "insufficient developer role", "app is in development",
                              "invalid platform app")):
        return OAuthError("not_tester", msg)
    return OAuthError("oauth_failed", msg)


async def _json(http: httpx.AsyncClient, method: str, url: str, **kw) -> dict:
    try:
        r = await http.request(method, url, **kw)
    except httpx.HTTPError as e:
        raise OAuthError("oauth_unreachable", str(e)) from e
    if r.status_code >= 400:
        raise _oauth_error(r)
    return r.json()


async def exchange(s: Settings, http: httpx.AsyncClient, platform: str, code: str, now_ms: int) -> Token:
    """code -> short-lived token -> long-lived token (60 days) + account info."""
    if s.dev_fake_providers:
        return Token(f"fake-token-{platform}", now_ms + 60 * 86_400_000, f"{platform}-17840000", f"fake_{platform}",
                     "BUSINESS")
    if platform == "instagram":
        short = await _json(http, "POST", "https://api.instagram.com/oauth/access_token", data={
            "client_id": s.meta_app_id, "client_secret": s.meta_app_secret, "grant_type": "authorization_code",
            "redirect_uri": redirect_uri(s, platform), "code": code})
        short = (short.get("data") or [short])[0]
        long = await _json(http, "GET", "https://graph.instagram.com/access_token", params={
            "grant_type": "ig_exchange_token", "client_secret": s.meta_app_secret,
            "access_token": short["access_token"]})
        me = await _json(http, "GET", f"https://graph.instagram.com/{s.meta_graph_version}/me", params={
            "fields": "user_id,username,account_type", "access_token": long["access_token"]})
        if me.get("account_type") not in (None, "BUSINESS", "MEDIA_CREATOR"):
            raise OAuthError("not_business", f"account type {me.get('account_type')}")
        return Token(long["access_token"], now_ms + int(long.get("expires_in", 5184000)) * 1000,
                     str(me.get("user_id") or short.get("user_id")), me.get("username", ""), me.get("account_type", ""))
    short = await _json(http, "POST", "https://graph.threads.net/oauth/access_token", data={
        "client_id": s.threads_app_id, "client_secret": s.threads_app_secret, "grant_type": "authorization_code",
        "redirect_uri": redirect_uri(s, platform), "code": code})
    long = await _json(http, "GET", "https://graph.threads.net/access_token", params={
        "grant_type": "th_exchange_token", "client_secret": s.threads_app_secret, "access_token": short["access_token"]})
    me = await _json(http, "GET", "https://graph.threads.net/v1.0/me", params={
        "fields": "id,username", "access_token": long["access_token"]})
    return Token(long["access_token"], now_ms + int(long.get("expires_in", 5184000)) * 1000,
                 str(me.get("id") or short.get("user_id")), me.get("username", ""))


async def refresh(s: Settings, http: httpx.AsyncClient, platform: str, token: str, now_ms: int) -> Token:
    if s.dev_fake_providers:
        return Token(token, now_ms + 60 * 86_400_000)
    url = ("https://graph.instagram.com/refresh_access_token", "ig_refresh_token") if platform == "instagram" else \
        ("https://graph.threads.net/refresh_access_token", "th_refresh_token")
    try:
        r = await http.get(url[0], params={"grant_type": url[1], "access_token": token})
    except httpx.HTTPError as e:
        raise PublishError("platform_unavailable", str(e), retryable=True) from e
    if r.status_code >= 400:
        raise graph_error(r)
    j = r.json()
    return Token(j["access_token"], now_ms + int(j.get("expires_in", 5184000)) * 1000)
