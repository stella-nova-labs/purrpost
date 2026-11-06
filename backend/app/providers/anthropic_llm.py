"""Claude through the official Anthropic SDK."""

from __future__ import annotations

import anthropic

from ..config import Settings
from .base import LLMResult, ProviderError
from .pricing import llm_usage

FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-1"}


class AnthropicLLM:
    def __init__(self, settings: Settings, api_key: str, billed_to: str = "shared", http_client=None) -> None:
        self.settings = settings
        self.billed_to = billed_to
        self.client = anthropic.AsyncAnthropic(api_key=api_key, timeout=180.0, max_retries=2,
                                               **({"http_client": http_client} if http_client else {}))

    async def complete(self, task: str, system: str, content: list[dict], max_tokens: int = 4000) -> LLMResult:
        s = self.settings
        kwargs: dict = {
            "model": s.anthropic_model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": content}],
            "output_config": {"effort": s.anthropic_effort},
        }
        if s.anthropic_fallbacks and s.anthropic_model in FALLBACK_MODELS:
            # Server-side refusal fallback: on a policy decline the API re-runs the request on another model
            kwargs["betas"] = ["server-side-fallback-2026-07-01"]
            kwargs["extra_body"] = {"fallbacks": "default"}
        try:
            msg = await self.client.beta.messages.create(**kwargs)
        except anthropic.AuthenticationError as e:
            raise ProviderError("anthropic_auth", "Anthropic key is invalid") from e
        except anthropic.RateLimitError as e:
            raise ProviderError("anthropic_rate_limit", str(e), retryable=True) from e
        except anthropic.BadRequestError as e:
            raise ProviderError("anthropic_bad_request", str(e)) from e
        except anthropic.APIStatusError as e:
            raise ProviderError("anthropic_error", str(e), retryable=e.status_code >= 500) from e
        except anthropic.APIConnectionError as e:
            raise ProviderError("anthropic_unreachable", str(e), retryable=True) from e
        if msg.stop_reason == "refusal":
            raise ProviderError("llm_refused", "the model declined this request")
        text = "".join(b.text for b in msg.content if b.type == "text")
        usage = llm_usage(s, task, msg.usage.input_tokens, msg.usage.output_tokens)
        usage.billed_to = self.billed_to
        return LLMResult(text=text, usage=usage)
