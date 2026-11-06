"""Shared HTTP for Meta's Graph APIs (Instagram API with Instagram Login, Threads)."""

from __future__ import annotations

import asyncio
import logging

import httpx

from .base import PublishError

log = logging.getLogger("purrpost.graph")

RATE_CODES = {4, 17, 32, 613, 80002}
TOKEN_CODES = {190, 102}
PERMISSION_CODES = {10, 200, 3}


def graph_error(r: httpx.Response) -> PublishError:
    try:
        err = r.json().get("error") or {}
    except ValueError:
        err = {}
    code, sub = err.get("code"), err.get("error_subcode")
    msg = err.get("error_user_msg") or err.get("message") or f"HTTP {r.status_code}"
    if code in TOKEN_CODES or sub in (463, 467):
        return PublishError("token_expired", msg, account_broken=True)
    if sub == 2207042 or "publishing limit" in str(msg).lower():
        return PublishError("publish_limit", msg, retryable=True, retry_after_ms=3 * 3600_000)
    if code in RATE_CODES or r.status_code == 429:
        return PublishError("rate_limited", msg, retryable=True, retry_after_ms=15 * 60_000)
    if code in PERMISSION_CODES:
        return PublishError("permission_denied", msg, account_broken=True)
    if sub in (2207052, 2207003, 2207020) or code == 9004:
        return PublishError("media_fetch_failed", msg, retryable=True)
    if r.status_code >= 500 or err.get("is_transient"):
        return PublishError("platform_unavailable", msg, retryable=True)
    return PublishError("platform_error", msg)


class Graph:
    def __init__(self, http: httpx.AsyncClient, base: str, poll_every: float = 3.0, poll_tries: int = 40) -> None:
        self.http, self.base = http, base.rstrip("/")
        self.poll_every, self.poll_tries = poll_every, poll_tries

    async def call(self, method: str, path: str, token: str, **params) -> dict:
        url = path if path.startswith("http") else f"{self.base}/{path.lstrip('/')}"
        data = {k: v for k, v in params.items() if v is not None}
        try:
            if method == "GET" or method == "DELETE":
                r = await self.http.request(method, url, params={**data, "access_token": token})
            else:
                r = await self.http.post(url, data={**data, "access_token": token})
        except httpx.HTTPError as e:
            raise PublishError("platform_unavailable", str(e), retryable=True) from e
        if r.status_code >= 400:
            raise graph_error(r)
        try:
            return r.json()
        except ValueError:
            return {}

    async def wait_ready(self, container: str, token: str, field: str = "status_code") -> str:
        """Containers are processed asynchronously: wait for FINISHED before publishing."""
        for _ in range(self.poll_tries):
            st = (await self.call("GET", container, token, fields=field)).get(field, "")
            if st in ("FINISHED", "PUBLISHED"):
                return st
            if st in ("ERROR", "EXPIRED"):
                raise PublishError("media_rejected", f"container {st}", retryable=False)
            await asyncio.sleep(self.poll_every)
        raise PublishError("platform_slow", "media processing took too long", retryable=True)
