"""Cost estimates per provider tariff (USD). Used for budgets; the provider's invoice is the truth.

fal.ai prices are per image or per megapixel (see each model page on fal.ai); update here if they change."""

from __future__ import annotations

from ..config import Settings
from .base import Usage

FAL_PER_MP = {
    "fal-ai/flux/dev": 0.025,
    "fal-ai/flux-lora": 0.035,
}
FAL_PER_IMAGE = {
    "fal-ai/flux-pro/kontext": 0.04,
}
LORA_TRAINING_RUN = 2.0


def megapixels(width: int, height: int) -> float:
    return round(width * height / 1_000_000, 3)


def image_usage(model: str, n: int, width: int, height: int, kind: str) -> Usage:
    if model in FAL_PER_IMAGE:
        cost = FAL_PER_IMAGE[model] * n
    else:
        cost = FAL_PER_MP.get(model, 0.035) * megapixels(width, height) * n
    return Usage("fal", kind, n, round(cost, 5))


def training_usage() -> Usage:
    return Usage("fal", "lora.training", 1, LORA_TRAINING_RUN)


def llm_usage(settings: Settings, task: str, tokens_in: int, tokens_out: int) -> Usage:
    cost = tokens_in / 1e6 * settings.anthropic_price_in + tokens_out / 1e6 * settings.anthropic_price_out
    return Usage("anthropic", f"llm.{task}", tokens_in + tokens_out, round(cost, 5))
