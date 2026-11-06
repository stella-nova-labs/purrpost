"""Fake publisher: nothing leaves the server. Used with DEV_FAKE_PROVIDERS=1 and in tests."""

from __future__ import annotations

import random

from .base import Creds, Post, Published, PublishError


class FakePublisher:
    needs_public_urls = False

    def __init__(self, platform: str) -> None:
        self.platform = platform
        self.posts: list[tuple[str, Post]] = []
        self.deleted: list[str] = []
        self.fail_with: list[PublishError] = []  # tests queue errors here

    async def publish(self, c: Creds, post: Post, state: dict) -> Published:
        if state.get("media_id"):
            return Published(state["media_id"], f"https://example.com/{self.platform}/{state['media_id']}")
        if self.fail_with:
            raise self.fail_with.pop(0)
        mid = f"{self.platform}-{len(self.posts) + 1}"
        self.posts.append((c.external_id, post))
        state["media_id"] = mid
        return Published(mid, f"https://example.com/{self.platform}/{mid}")

    async def delete(self, c: Creds, external_id: str, state: dict) -> None:
        self.deleted.append(external_id)

    async def metrics(self, c: Creds, external_id: str) -> dict:
        rng = random.Random(external_id)
        reach = rng.randint(300, 4000)
        return {"likes": int(reach * rng.uniform(0.05, 0.2)), "comments": rng.randint(2, 60), "reach": reach,
                "saves": rng.randint(5, 120)}

    async def account_stats(self, c: Creds) -> dict:
        return {"followers": random.Random(c.external_id).randint(200, 5000)}
