"""Threads API: the same container -> publish flow. Text up to 500 characters, one hashtag at most."""

from __future__ import annotations

import re

import httpx

from .base import Creds, Post, Published, PublishError
from .graph import Graph

LIMIT = 500


def threads_text(caption: str) -> str:
    """Threads allows a single topic tag: drop the hashtag block, keep the text and the AI disclosure."""
    parts = [p for p in caption.split("\n\n") if not re.fullmatch(r"(#\w+\s*)+", p.strip())]
    text = "\n\n".join(parts)
    return text if len(text) <= LIMIT else text[:LIMIT - 1].rstrip() + "…"


class ThreadsPublisher:
    platform = "threads"
    needs_public_urls = True

    def __init__(self, http: httpx.AsyncClient, poll_every: float = 3.0) -> None:
        self.g = Graph(http, "https://graph.threads.net/v1.0", poll_every=poll_every)

    async def publish(self, c: Creds, post: Post, state: dict) -> Published:
        if state.get("media_id"):
            return Published(state["media_id"], await self._permalink(c, state["media_id"]))
        text = threads_text(post.caption)
        if not state.get("container"):
            if len(post.media) == 1:
                res = await self.g.call("POST", f"{c.external_id}/threads", c.token, media_type="IMAGE",
                                        image_url=post.media[0].url, text=text, alt_text=post.alt_text[:1000] or None)
            else:
                children = state.setdefault("children", [])
                for m in post.media[len(children):10]:
                    r = await self.g.call("POST", f"{c.external_id}/threads", c.token, media_type="IMAGE",
                                          image_url=m.url, is_carousel_item="true")
                    children.append(r["id"])
                for child in children:
                    await self.g.wait_ready(child, c.token, field="status")
                res = await self.g.call("POST", f"{c.external_id}/threads", c.token, media_type="CAROUSEL",
                                        children=",".join(children), text=text)
            state["container"] = res["id"]
        try:
            await self.g.wait_ready(state["container"], c.token, field="status")
        except PublishError as e:
            if e.code == "media_rejected":
                state.clear()
                e.retryable = True
            raise
        mid = (await self.g.call("POST", f"{c.external_id}/threads_publish", c.token,
                                 creation_id=state["container"]))["id"]
        state["media_id"] = mid
        return Published(mid, await self._permalink(c, mid))

    async def _permalink(self, c: Creds, mid: str) -> str | None:
        try:
            return (await self.g.call("GET", mid, c.token, fields="permalink")).get("permalink")
        except PublishError:
            return None

    async def delete(self, c: Creds, external_id: str, state: dict) -> None:
        await self.g.call("DELETE", external_id, c.token)

    async def metrics(self, c: Creds, external_id: str) -> dict:
        res = await self.g.call("GET", f"{external_id}/insights", c.token, metric="views,likes,replies,reposts")
        out = {}
        for row in res.get("data", []):
            v = (row.get("values") or [{}])[0].get("value", (row.get("total_value") or {}).get("value"))
            out[{"replies": "comments"}.get(row["name"], row["name"])] = v
        return out

    async def account_stats(self, c: Creds) -> dict:
        try:
            res = await self.g.call("GET", f"{c.external_id}/threads_insights", c.token, metric="followers_count")
            row = (res.get("data") or [{}])[0]
            return {"followers": (row.get("total_value") or {}).get("value")}
        except PublishError:
            return {}
