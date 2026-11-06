"""Content pipeline: plan (Claude) -> images (Flux + LoRA, 2 variants per slide) -> QA (Claude vision) -> draft."""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Character, CharacterImage, Draft, Job, User
from ..providers import registry
from . import budget, prompts
from .content_filter import find_blocked
from .llm_json import ask_json
from .queue import JobFailed, handler
from .schedule import zone
from .users import now_ms

log = logging.getLogger("purrpost.pipeline")

POST_SIZE = (1080, 1350)  # 4:5
VARIANTS = 2
MAX_REGENERATIONS = 2  # extra rounds per slide after the first


class Slide(BaseModel):
    scene: str = Field(min_length=3, max_length=1200)


class PostPlan(BaseModel):
    idea: str = Field(min_length=3, max_length=500)
    slides: list[Slide] = Field(min_length=1, max_length=5)
    caption: str = Field(min_length=1, max_length=2000)
    hashtags: list[str] = Field(min_length=5, max_length=15)
    alt_text: str = Field("", max_length=1000)
    summary: str = Field("", max_length=300)

    @field_validator("hashtags")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        out = []
        for t in v:
            t = "#" + re.sub(r"[^\w]", "", t.lstrip("#"))
            if len(t) > 1 and t.lower() not in (x.lower() for x in out):
                out.append(t)
        if len(out) < 5:
            raise ValueError("need at least 5 distinct hashtags")
        return out[:15]


class QAVerdict(BaseModel):
    anatomy_ok: bool
    matches_reference: bool
    text_artifacts: bool
    logos_or_known_characters: bool
    weapons: bool = False
    issues: list[str] = Field(default_factory=list)
    score: float = Field(0.5, ge=0, le=1)

    @property
    def ok(self) -> bool:
        # decided here, not by the model's own "ok"
        return (self.anatomy_ok and self.matches_reference and not self.text_artifacts
                and not self.logos_or_known_characters and not self.weapons)


def bible(ch: Character) -> dict:
    return {"name": ch.name, "handle": ch.handle, "personality": ch.personality, "pain": ch.pain,
            "humor": ch.humor, "caption_language": ch.language, "looks": ch.appearance_text or ch.appearance,
            "rubrics": ch.rubrics, "stop_topics": ch.stop_topics, "notes": ch.notes}


def final_caption(d: Draft, ch: Character) -> str:
    """What gets published: caption, hashtags and the AI disclosure line (on by default)."""
    parts = [d.caption.strip()]
    if d.hashtags:
        parts.append(" ".join(d.hashtags))
    if ch.ai_disclosure and ch.disclosure_text.strip():
        parts.append(ch.disclosure_text.strip())
    return "\n\n".join(p for p in parts if p)


def remember(ch: Character, d: Draft) -> None:
    """Add the post to the character's story log (last 30), so stories continue and don't repeat."""
    date = datetime.fromtimestamp(d.slot_ms / 1000, zone(ch.schedule.get("tz", "UTC"))).strftime("%Y-%m-%d")
    lore = [x for x in (ch.lore or []) if x.get("draft_id") != d.id]
    lore.append({"draft_id": d.id, "date": date, "rubric": d.rubric, "summary": d.summary or d.idea})
    ch.lore = lore[-30:]


async def _reference(ctx, s: AsyncSession, ch: Character) -> bytes:
    img = await s.get(CharacterImage, ch.chosen_image_id) if ch.chosen_image_id else None
    if img is None:
        raise JobFailed("no_reference")
    return await ctx.storage.get(img.key)


async def _load(s: AsyncSession, job: Job) -> tuple[Draft, Character, User]:
    d = await s.get(Draft, job.draft_id)
    if d is None:
        raise JobFailed("draft_gone")
    ch = await s.get(Character, d.character_id)
    u = await s.get(User, d.user_id)
    if ch is None or ch.archived or not ch.lora_url:
        raise JobFailed("character_not_ready")
    return d, ch, u


async def make_slide(ctx, s: AsyncSession, p, u: User, ch: Character, d: Draft, scene: str, ref: bytes,
                     index: int) -> dict:
    """Generate 2 variants, QA both, keep the best passing one. Up to 2 more rounds if none passes; then keep
    the best-scoring variant and mark the slide for review."""
    blocked = find_blocked(scene)
    best: tuple[float, bytes, QAVerdict] | None = None
    attempts = 0
    for rnd in range(1 + MAX_REGENERATIONS):
        await budget.ensure(s, ctx, u, p)
        prompt = prompts.lora_prompt(ch.lora_trigger, ch.appearance_text, scene)
        res = await p.images.generate_lora(prompt, ch.lora_url, VARIANTS, *POST_SIZE,
                                           seed=d.id * 1000 + index * 10 + rnd)
        budget.record(s, u.id, res.usage, ch.id)
        attempts += 1
        for data in res.images:
            usages: list = []
            v = await ask_json(p.llm, "qa", prompts.QA_SYSTEM,
                               prompts.qa_content(ref, data, scene, ch.appearance_text), QAVerdict, usages.append,
                               max_tokens=1500)
            for x in usages:
                budget.record(s, u.id, x, ch.id)
            score = v.score + (1 if v.ok else 0)
            if best is None or score > best[0]:
                best = (score, data, v)
        await s.commit()
        if best and best[2].ok:
            break
    _, data, verdict = best  # type: ignore[misc]
    key = f"u{u.id}/c{ch.id}/d{d.id}/{index}-{uuid.uuid4().hex[:10]}.jpg"
    await ctx.storage.put(key, data, "image/jpeg")
    issues = list(verdict.issues)
    if blocked:
        issues.append("scene mentions: " + ", ".join(blocked))
    return {"scene": scene, "key": key, "ok": verdict.ok and not blocked, "attempts": attempts,
            "qa": {"score": verdict.score, "issues": issues[:6]}}


def _final_status(ch: Character, d: Draft) -> str:
    d.qa_ok = all(sl.get("ok") for sl in d.slides)
    if not d.qa_ok:
        return "needs_review"
    return "scheduled" if ch.autopilot else "pending_review"


async def _after_generation(ctx, s: AsyncSession, ch: Character, d: Draft) -> None:
    d.status = _final_status(ch, d)
    if d.status == "scheduled":
        d.approved_ms = now_ms()
    await s.commit()
    from .drafts import notify_draft
    await notify_draft(ctx, s, d, ch)


@handler("plan")
async def plan_post(ctx, job: Job) -> None:
    async with ctx.db.sessions() as s:
        d, ch, u = await _load(s, job)
        if d.status != "generating":
            return  # already done (e.g. job retried after a crash)
        p = registry.for_user(ctx, u)
        await budget.ensure(s, ctx, u, p)
        from .schedule import rubric_for
        usages: list = []
        plan = await ask_json(
            p.llm, "post_plan", prompts.plan_system(ch.slides_max),
            prompts.plan_content(bible(ch), [{k: v for k, v in x.items() if k != "draft_id"} for x in ch.lore[-30:]],
                                 rubric_for(ch, d.slot_ms), d.trend, ch.slides_max),
            PostPlan, usages.append, max_tokens=4000)
        for x in usages:
            budget.record(s, u.id, x, ch.id)
        d.idea, d.caption, d.hashtags = plan.idea, plan.caption.strip(), plan.hashtags
        d.alt_text, d.summary = plan.alt_text, plan.summary
        await s.commit()
        ref = await _reference(ctx, s, ch)
        slides = []
        for i, sl in enumerate(plan.slides[:ch.slides_max]):
            slides.append(await make_slide(ctx, s, p, u, ch, d, sl.scene, ref, i))
            d.slides = list(slides)
            await s.commit()
        await _after_generation(ctx, s, ch, d)


@handler("regen_images")
async def regenerate_images(ctx, job: Job) -> None:
    """New images for the same plan (the caption stays)."""
    async with ctx.db.sessions() as s:
        d, ch, u = await _load(s, job)
        p = registry.for_user(ctx, u)
        await budget.ensure(s, ctx, u, p)
        ref = await _reference(ctx, s, ch)
        only = job.payload.get("slides")  # indexes, or None for all
        slides = list(d.slides)
        for i, sl in enumerate(slides):
            if only is None or i in only:
                slides[i] = await make_slide(ctx, s, p, u, ch, d, sl["scene"], ref, i + 100 * (job.attempts + 1))
                d.slides = list(slides)
                await s.commit()
        await _after_generation(ctx, s, ch, d)


async def _on_fail(ctx, job: Job, code: str) -> None:
    async with ctx.db.sessions() as s:
        d = await s.get(Draft, job.draft_id) if job.draft_id else None
        if d is not None and d.status in ("generating", "regenerating"):
            d.status, d.error = "failed", code
            await s.commit()
    if code != "budget_exceeded":
        from .notify_texts import job_failed
        await ctx.notifier.send(job.user_id, job_failed(job.kind, code))


plan_post.on_fail = _on_fail  # type: ignore[attr-defined]
regenerate_images.on_fail = _on_fail  # type: ignore[attr-defined]
