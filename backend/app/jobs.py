"""Background work: one `tick` runs every step once. The worker service calls it in a loop."""

from __future__ import annotations

import asyncio
import logging

from .context import Ctx
from .services import characters, metrics, pipeline, publishing, queue, schedule  # noqa: F401 (pipeline registers handlers)

log = logging.getLogger("purrpost.jobs")

STEPS: list = [
    ("planner", schedule.plan),
    ("queue", queue.process),
    ("trainings", characters.poll_trainings),
    ("publish_due", publishing.start_due),
    ("publish", publishing.process),
    ("tokens", publishing.refresh_tokens),
    ("metrics", metrics.collect),
    ("followers", metrics.account_stats),
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
