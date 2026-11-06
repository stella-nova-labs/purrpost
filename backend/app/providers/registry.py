"""Which provider instance serves a user: fakes in dev, the user's own keys if set, else the shared keys."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from ..models import User
from ..services.crypto import decrypt
from .base import LLM, ImageGen, LoraTrainer, ProviderError


@dataclass
class Providers:
    llm: LLM
    images: ImageGen
    trainer: LoraTrainer

    @property
    def any_shared(self) -> bool:
        return "shared" in (self.llm.billed_to, self.images.billed_to, self.trainer.billed_to)


class _Missing:
    """Placeholder when no key is configured: fails with a clear code on first use."""

    billed_to = "shared"

    def __init__(self, code: str) -> None:
        self.code = code

    def __getattr__(self, name):
        async def fail(*a, **kw):
            raise ProviderError(self.code, "provider is not configured")
        return fail


def for_user(ctx, user: User | None) -> Providers:
    s = ctx.settings
    if s.dev_fake_providers:
        f = ctx.fakes
        return Providers(f["llm"], f["images"], f["trainer"])
    from .anthropic_llm import AnthropicLLM
    from .fal import FalClient, FalTrainer

    own_anthropic = decrypt(s, user.anthropic_key_enc) if user else None
    own_fal = decrypt(s, user.fal_key_enc) if user else None
    if own_anthropic:
        llm = AnthropicLLM(s, own_anthropic, "own")
    elif s.anthropic_api_key:
        llm = AnthropicLLM(s, s.anthropic_api_key, "shared")
    else:
        llm = _Missing("anthropic_not_configured")
    http: httpx.AsyncClient = ctx.http
    if own_fal:
        fal = FalClient(s, own_fal, "own", http=http)
    elif s.fal_key:
        fal = FalClient(s, s.fal_key, "shared", http=http)
    else:
        missing = _Missing("fal_not_configured")
        return Providers(llm, missing, missing)  # type: ignore[arg-type]
    return Providers(llm, fal, FalTrainer(fal))
