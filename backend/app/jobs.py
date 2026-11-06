"""Background work: one `tick` runs every step once. The worker service calls it in a loop."""

from __future__ import annotations

import asyncio
import logging

from .context import Ctx
from .services import characters, queue

log = logging.getLogger("purrpost.jobs")

STEPS: list = [
    ("queue", queue.process),
    ("trainings", characters.poll_trainings),
]


async def tick(ctx: Ctx) -> dict:
    """Run every step once. One failing integration doesn't stop the others."""
    out: dict = {}
    for name, fn in STEPS:
        try:
            out[name] = await fn(ctx)
        except Exception:  # noqa: BLE001
            log.exception("job %s failed", name)
            out[name] = "error"
    return out


async def loop(ctx: Ctx) -> None:
    while True:
        await tick(ctx)
        await asyncio.sleep(ctx.settings.worker_interval_sec)
