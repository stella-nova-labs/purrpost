"""Publishing interface. Each platform is a class; TikTok can be added later as one more."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class PublishError(Exception):
    """`code` maps to a clear message in the app and the bot. `retryable` errors are retried with backoff;
    `retry_after_ms` asks for a specific delay (e.g. the 24 h publishing limit)."""

    def __init__(self, code: str, message: str = "", retryable: bool = False, retry_after_ms: int | None = None,
                 account_broken: bool = False) -> None:
        super().__init__(message or code)
        self.code, self.message = code, message or code
        self.retryable, self.retry_after_ms, self.account_broken = retryable, retry_after_ms, account_broken


@dataclass
class Creds:
    external_id: str
    token: str | None
    username: str = ""
    meta: dict = field(default_factory=dict)


@dataclass
class Media:
    url: str  # public URL (Instagram and Threads fetch images themselves)
    data: bytes | None = None  # raw bytes (Telegram uploads them)


@dataclass
class Post:
    media: list[Media]
    caption: str
    alt_text: str = ""


@dataclass
class Published:
    external_id: str
    permalink: str | None = None


class Publisher(Protocol):
    platform: str
    needs_public_urls: bool

    async def publish(self, creds: Creds, post: Post, state: dict) -> Published:
        """Publish. `state` is saved after every call, also on errors; write progress into it (container ids,
        the media id) and check it first, so that a retry never creates a second post."""
        ...

    async def delete(self, creds: Creds, external_id: str, state: dict) -> None: ...

    async def metrics(self, creds: Creds, external_id: str) -> dict:
        """likes, comments, reach, saves, views... whatever the platform gives; missing keys are fine."""
        ...

    async def account_stats(self, creds: Creds) -> dict:
        """followers etc."""
        ...
