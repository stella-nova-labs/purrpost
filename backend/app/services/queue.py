"""A small job queue in the database. Any process can enqueue; workers claim jobs atomically, so a job runs
once even with several worker processes."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Job
from ..providers.base import ProviderError
from .budget import BudgetExceeded
from .llm_json import LLMJSONError
from .users import now_ms

log = logging.getLogger("purrpost.queue")

Handler = Callable[..., Awaitable[None]]
HANDLERS: dict[str, Handler] = {}
MAX_ATTEMPTS = 3


def handler(kind: str):
    def deco(fn: Handler) -> Handler:
        HANDLERS[kind] = fn
        return fn
    return deco


class JobFailed(Exception):
    """Raise from a handler to fail the job with a user-facing code (no retry)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


async def enqueue(s: AsyncSession, kind: str, user_id: int, *, character_id: int | None = None,
                  draft_id: int | None = None, payload: dict | None = None, dedupe_key: str | None = None,
                  run_after_ms: int = 0) -> Job | None:
    """Add a job. With a dedupe_key that already exists, nothing is added and None is returned."""
    job = Job(kind=kind, user_id=user_id, character_id=character_id, draft_id=draft_id, payload=payload or {},
              dedupe_key=dedupe_key, run_after_ms=run_after_ms, created_ms=now_ms())
    try:
        async with s.begin_nested():
            s.add(job)
    except IntegrityError:
        return None
    return job


async def busy(s: AsyncSession, *, character_id: int | None = None, draft_id: int | None = None) -> list[str]:
    q = select(Job.kind).where(Job.status.in_(("queued", "running")))
    if character_id is not None:
        q = q.where(Job.character_id == character_id)
    if draft_id is not None:
        q = q.where(Job.draft_id == draft_id)
    return list((await s.execute(q)).scalars())


async def last_error(s: AsyncSession, character_id: int) -> Job | None:
    return (await s.execute(select(Job).where(Job.character_id == character_id).order_by(Job.id.desc()).limit(1))
            ).scalar_one_or_none()


async def _claim(ctx, now: int) -> Job | None:
    async with ctx.db.sessions() as s:
        ids = (await s.execute(select(Job.id).where(Job.status == "queued", Job.run_after_ms <= now)
                               .order_by(Job.id).limit(5))).scalars().all()
        for jid in ids:
            res = await s.execute(update(Job).where(Job.id == jid, Job.status == "queued")
                                  .values(status="running", attempts=Job.attempts + 1))
            if res.rowcount == 1:
                await s.commit()
                return await s.get(Job, jid)
    return None


async def _finish(ctx, job_id: int, status: str, error: str | None = None, retry_at: int | None = None) -> None:
    async with ctx.db.sessions() as s:
        job = await s.get(Job, job_id)
        if retry_at is not None:
            job.status, job.run_after_ms, job.error = "queued", retry_at, error
        else:
            job.status, job.error, job.finished_ms = status, error, now_ms()
            if status in ("done", "failed") and job.dedupe_key:
                # free the key so the same work can be requested again later
                job.dedupe_key = f"{job.dedupe_key}#{job.id}"[:80]
        await s.commit()


async def run_one(ctx, job: Job) -> None:
    fn = HANDLERS.get(job.kind)
    if fn is None:
        await _finish(ctx, job.id, "failed", f"unknown job kind {job.kind}")
        return
    on_fail = getattr(fn, "on_fail", None)
    try:
        await fn(ctx, job)
    except BudgetExceeded:
        await _finish(ctx, job.id, "failed", "budget_exceeded")
        code = "budget_exceeded"
    except JobFailed as e:
        await _finish(ctx, job.id, "failed", e.code)
        code = e.code
    except ProviderError as e:
        if e.retryable and job.attempts < MAX_ATTEMPTS:
            delay = 30_000 * 2 ** (job.attempts - 1)
            log.warning("job %s %s: %s, retry in %ss", job.id, job.kind, e.code, delay // 1000)
            await _finish(ctx, job.id, "queued", e.code, retry_at=now_ms() + delay)
            return
        await _finish(ctx, job.id, "failed", e.code)
        code = e.code
    except LLMJSONError as e:
        log.warning("job %s %s: %s", job.id, job.kind, e)
        await _finish(ctx, job.id, "failed", "llm_bad_json")
        code = "llm_bad_json"
    except Exception:  # noqa: BLE001
        log.exception("job %s %s crashed", job.id, job.kind)
        await _finish(ctx, job.id, "failed", "internal_error")
        code = "internal_error"
    else:
        await _finish(ctx, job.id, "done")
        return
    if on_fail:
        try:
            await on_fail(ctx, job, code)
        except Exception:  # noqa: BLE001
            log.exception("on_fail of job %s", job.id)


async def process(ctx, limit: int = 20) -> int:
    """Run queued jobs until none are due (or `limit`). Returns how many ran."""
    n = 0
    while n < limit:
        job = await _claim(ctx, now_ms())
        if job is None:
            break
        await run_one(ctx, job)
        n += 1
    return n


_kick_lock = asyncio.Lock()


def kick(ctx) -> None:
    """Start processing right away in this process (no wait for the next worker tick). Only when the worker
    runs inside the web process; otherwise the worker service picks the job up within WORKER_INTERVAL_SEC."""
    if not ctx.settings.run_worker:
        return

    async def go() -> None:
        if _kick_lock.locked():
            return
        async with _kick_lock:
            await process(ctx)

    task = asyncio.get_running_loop().create_task(go())
    ctx.__dict__.setdefault("_tasks", set()).add(task)
    task.add_done_callback(ctx.__dict__["_tasks"].discard)
