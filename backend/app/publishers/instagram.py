"""Instagram API with Instagram Login: content publishing (photo and carousel up to 10)."""

from __future__ import annotations

import httpx

from ..config import Settings
from .base import Creds, Post, Published, PublishError
from .graph import Graph


class InstagramPublisher:
    platform = "instagram"
    needs_public_urls = True

    def __init__(self, settings: Settings, http: httpx.AsyncClient, poll_every: float = 3.0) -> None:
        self.g = Graph(http, f"https://graph.instagram.com/{settings.meta_graph_version}", poll_every=poll_every)

    async def check_limit(self, c: Creds) -> None:
        """Instagram allows a limited number of API posts per 24 h (content_publishing_limit)."""
        res = await self.g.call("GET", f"{c.external_id}/content_publishing_limit", c.token,
                                fields="quota_usage,config")
        rows = res.get("data") or []
        if not rows:
            return
        used = rows[0].get("quota_usage", 0)
        total = (rows[0].get("config") or {}).get("quota_total", 100)
        if used >= total:
            raise PublishError("publish_limit", f"{used}/{total} posts in 24 h", retryable=True,
                               retry_after_ms=3 * 3600_000)

    async def _find_published(self, c: Creds, caption: str) -> str | None:
        """The container says PUBLISHED but we lost the media id (crash): find the post by caption."""
        res = await self.g.call("GET", f"{c.external_id}/media", c.token, fields="id,caption", limit=10)
        for m in res.get("data", []):
            if (m.get("caption") or "").strip() == caption.strip():
                return m["id"]
        return None

    async def publish(self, c: Creds, post: Post, state: dict) -> Published:
        if state.get("media_id"):  # published already, only the permalink is missing
            return Published(state["media_id"], await self._permalink(c, state["media_id"]))
        if not state.get("container"):
            await self.check_limit(c)
            alt = post.alt_text[:1000] or None
            if len(post.media) == 1:
                res = await self.g.call("POST", f"{c.external_id}/media", c.token, image_url=post.media[0].url,
                                        caption=post.caption, alt_text=alt)
                state["container"] = res["id"]
            else:
                children = state.setdefault("children", [])
                for m in post.media[len(children):10]:
                    res = await self.g.call("POST", f"{c.external_id}/media", c.token, image_url=m.url,
                                            is_carousel_item="true", alt_text=alt)
                    children.append(res["id"])
                for child in children:
                    await self.g.wait_ready(child, c.token)
                res = await self.g.call("POST", f"{c.external_id}/media", c.token, media_type="CAROUSEL",
                                        children=",".join(children), caption=post.caption)
                state["container"] = res["id"]
        try:
            st = await self.g.wait_ready(state["container"], c.token)
        except PublishError as e:
            if e.code == "media_rejected":
                state.clear()  # the container is dead: next attempt starts over
                e.retryable = True
            raise
        if st == "PUBLISHED":
            mid = await self._find_published(c, post.caption)
            if mid is None:
                raise PublishError("unknown_state", "container published but the post was not found")
        else:
            mid = (await self.g.call("POST", f"{c.external_id}/media_publish", c.token,
                                     creation_id=state["container"]))["id"]
        state["media_id"] = mid
        return Published(mid, await self._permalink(c, mid))

    async def _permalink(self, c: Creds, mid: str) -> str | None:
        try:
            return (await self.g.call("GET", mid, c.token, fields="permalink")).get("permalink")
        except PublishError:
            return None

    async def delete(self, c: Creds, external_id: str, state: dict) -> None:
        try:
            await self.g.call("DELETE", external_id, c.token)
        except PublishError as e:
            if e.code in ("platform_error", "permission_denied"):
                raise PublishError("delete_not_supported", e.message) from e
            raise

    async def metrics(self, c: Creds, external_id: str) -> dict:
        out: dict = {}
        base = await self.g.call("GET", external_id, c.token, fields="like_count,comments_count")
        out["likes"], out["comments"] = base.get("like_count"), base.get("comments_count")
        try:
            ins = await self.g.call("GET", f"{external_id}/insights", c.token, metric="reach,saved,shares,views")
            for row in ins.get("data", []):
                v = (row.get("values") or [{}])[0].get("value", (row.get("total_value") or {}).get("value"))
                out[{"saved": "saves"}.get(row["name"], row["name"])] = v
        except PublishError:
            pass  # insights need instagram_business_manage_insights; likes and comments still work
        return {k: v for k, v in out.items() if v is not None}

    async def account_stats(self, c: Creds) -> dict:
        me = await self.g.call("GET", "me", c.token, fields="followers_count,media_count,username")
        return {"followers": me.get("followers_count"), "posts": me.get("media_count")}
