"""Interfaces of external services. Real clients and fakes implement the same Protocols."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol


class ProviderError(Exception):
    """A provider call failed. `code` is shown to users as a short explanation."""

    def __init__(self, code: str, message: str = "", retryable: bool = False) -> None:
        super().__init__(message or code)
        self.code = code
        self.retryable = retryable


@dataclass
class Usage:
    provider: str
    kind: str
    units: float
    cost_usd: float
    billed_to: str = "shared"


@dataclass
class LLMResult:
    text: str
    usage: Usage


@dataclass
class ImageResult:
    images: list[bytes]
    usage: Usage
    content_type: str = "image/jpeg"


@dataclass
class TrainingStatus:
    state: Literal["queued", "running", "done", "failed"]
    lora_url: str | None = None
    error: str | None = None
    logs: list[str] = field(default_factory=list)


class LLM(Protocol):
    billed_to: str

    async def complete(self, task: str, system: str, content: list[dict], max_tokens: int = 4000) -> LLMResult:
        """`content` is a list of Messages API content blocks (text and base64 images).
        `task` names the call for usage accounting and lets the fake return a canned answer."""
        ...


class ImageGen(Protocol):
    billed_to: str

    async def generate(self, prompt: str, n: int, width: int, height: int, seed: int | None = None) -> ImageResult:
        """Text to image (appearance candidates)."""
        ...

    async def edit(self, image: bytes, prompt: str, seed: int | None = None) -> ImageResult:
        """One image from a reference image and an instruction (reference sheet)."""
        ...

    async def generate_lora(self, prompt: str, lora_url: str, n: int, width: int, height: int,
                            seed: int | None = None) -> ImageResult:
        """Text to image with the character's LoRA (posts, test images)."""
        ...


class LoraTrainer(Protocol):
    billed_to: str

    async def submit(self, zip_url: str, trigger_word: str) -> tuple[dict, Usage]:
        """Start training. Returns a handle (stored on the character) used by `status`."""
        ...

    async def status(self, handle: dict) -> TrainingStatus: ...


class Storage(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...

    def url(self, key: str, ttl: int | None = None) -> str:
        """A URL anyone can fetch for `ttl` seconds (public or presigned). Instagram needs this."""
        ...

    @property
    def public(self) -> bool:
        """True if `url()` is reachable from the internet (S3), False for local dev storage."""
        ...
