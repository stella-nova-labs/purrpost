"""Character wizard: card -> looks -> reference sheet -> LoRA training -> test images -> ready."""

from __future__ import annotations

import io
import logging
import re
import uuid
import zipfile

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Character, CharacterImage, Job, User
from ..providers import registry
from . import budget, prompts
from .content_filter import check_character, find_blocked
from .llm_json import ask_json
from .notify import Button
from .queue import JobFailed, enqueue, handler
from .templates import card as template_card
from .users import now_ms

log = logging.getLogger("purrpost.characters")

CANDIDATE_SIZE = (1024, 1024)
TEST_SIZE = (1080, 1350)
MIN_REFS = 10
DEFAULT_SCHEDULE = {"times": ["18:00"], "days": [0, 1, 2, 3, 4, 5, 6], "tz": "America/New_York", "lead_hours": 6}


class CardError(Exception):
    def __init__(self, code: str, detail: list[str] | None = None) -> None:
        super().__init__(code)
        self.code, self.detail = code, detail or []


# ---------- the card (step 1) ----------

class Rubric(BaseModel):
    weekday: int | None = Field(None, ge=0, le=6)
    title: str = Field(max_length=80)
    description: str = Field("", max_length=400)


class Appearance(BaseModel):
    breed: str = Field("", max_length=120)
    color: str = Field("", max_length=160)
    marks: str = Field("", max_length=240)
    signature: str = Field("", max_length=200)


class Card(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    handle: str = Field(min_length=1, max_length=40)
    personality: str = Field("", max_length=1200)
    pain: str = Field("", max_length=600)
    humor: str = Field("", max_length=200)
    language: str = Field("en", max_length=8)
    appearance: Appearance = Appearance()
    rubrics: list[Rubric] = Field(default_factory=list, max_length=10)
    stop_topics: list[str] = Field(default_factory=list, max_length=20)
    notes: str = Field("", max_length=1200)

    @field_validator("handle")
    @classmethod
    def _handle(cls, v: str) -> str:
        v = v.strip().lstrip("@").lower()
        if not re.fullmatch(r"[a-z0-9._]{1,30}", v):
            raise ValueError("handle: letters, digits, dots and underscores, up to 30")
        return v


class Suggestion(Card):
    refused: str | None = None
    name: str = Field("", max_length=80)
    handle: str = Field("cat", max_length=40)


def trigger_for(handle: str) -> str:
    return "PRP_" + (re.sub(r"[^a-z0-9]", "", handle.lower()) or "cat")[:24]


def _check(c: Card) -> None:
    hits = check_character(c.name, c.handle, c.appearance.model_dump())
    if hits:
        raise CardError("content_blocked", hits)


async def suggest(ctx, s: AsyncSession, user: User, idea: str) -> dict:
    """Claude fills a card from a one-line idea. The user edits it before saving."""
    if find_blocked(idea):
        raise CardError("content_blocked", find_blocked(idea))
    p = registry.for_user(ctx, user)
    await budget.ensure(s, ctx, user, p)
    usages: list = []
    sug = await ask_json(p.llm, "suggest_character", prompts.SUGGEST_SYSTEM, prompts.suggest_content(idea),
                         Suggestion, usages.append)
    for u in usages:
        budget.record(s, user.id, u)
    await s.commit()
    if sug.refused:
        raise CardError("content_refused", [sug.refused])
    data = sug.model_dump(exclude={"refused"})
    hits = check_character(sug.name, sug.handle, data["appearance"])
    if hits:
        raise CardError("content_blocked", hits)
    return data


def _apply(ch: Character, c: Card) -> None:
    ch.name, ch.handle, ch.personality, ch.pain, ch.humor = c.name, c.handle, c.personality, c.pain, c.humor
    ch.language, ch.notes = c.language or "en", c.notes
    ch.appearance = c.appearance.model_dump()
    ch.rubrics = [r.model_dump() for r in c.rubrics]
    ch.stop_topics = [t.strip() for t in c.stop_topics if t.strip()]


async def create(s: AsyncSession, user: User, c: Card, template_slug: str | None = None) -> Character:
    _check(c)
    ch = Character(user_id=user.id, template_slug=template_slug, status="appearance", created_ms=now_ms(),
                   schedule=dict(DEFAULT_SCHEDULE), lore=[], lora_trigger=trigger_for(c.handle))
    _apply(ch, c)
    s.add(ch)
    await s.flush()
    return ch


async def create_from_template(s: AsyncSession, user: User, slug: str) -> Character:
    data = template_card(slug)
    if data is None:
        raise CardError("template_not_found")
    return await create(s, user, Card.model_validate(data), template_slug=slug)


async def update_card(s: AsyncSession, ch: Character, c: Card) -> Character:
    _check(c)
    looks_changed = c.appearance.model_dump() != (ch.appearance or {})
    _apply(ch, c)
    if ch.status in ("appearance", "refsheet") and looks_changed:
        ch.appearance_text = ""
    if not ch.lora_url:
        ch.lora_trigger = trigger_for(c.handle)
    await s.flush()
    return ch


# ---------- images ----------

async def images(s: AsyncSession, ch: Character, kind: str | None = None) -> list[CharacterImage]:
    q = select(CharacterImage).where(CharacterImage.character_id == ch.id, CharacterImage.deleted.is_(False))
    if kind:
        q = q.where(CharacterImage.kind == kind)
    return list((await s.execute(q.order_by(CharacterImage.id))).scalars())


async def _store(ctx, s: AsyncSession, ch: Character, kind: str, data: bytes, prompt: str, batch: int,
                 ext: str = "jpg") -> CharacterImage:
    key = f"u{ch.user_id}/c{ch.id}/{kind}/{uuid.uuid4().hex}.{ext}"
    await ctx.storage.put(key, data, "image/jpeg")
    img = CharacterImage(character_id=ch.id, kind=kind, key=key, prompt=prompt[:2000], batch=batch, created_ms=now_ms())
    s.add(img)
    return img


async def _next_batch(s: AsyncSession, ch: Character, kind: str) -> int:
    rows = (await s.execute(select(CharacterImage.batch).where(CharacterImage.character_id == ch.id,
                                                              CharacterImage.kind == kind))).scalars().all()
    return max(rows, default=0) + 1


def _web_app_button(ctx, text: str = "Открыть Purrpost") -> list[list[Button]]:
    return [[Button(text, web_app=ctx.settings.webapp_url)]] if ctx.settings.webapp_url else []


async def _load(s: AsyncSession, job: Job) -> tuple[Character, User]:
    ch = await s.get(Character, job.character_id)
    u = await s.get(User, job.user_id)
    if ch is None or u is None or ch.archived:
        raise JobFailed("character_gone")
    return ch, u


# step 2: candidates

async def request_candidates(s: AsyncSession, ch: Character, count: int, extra: str) -> Job | None:
    return await enqueue(s, "candidates", ch.user_id, character_id=ch.id,
                         payload={"count": max(4, min(12, count)), "extra": extra[:400]},
                         dedupe_key=f"candidates:{ch.id}")


@handler("candidates")
async def gen_candidates(ctx, job: Job) -> None:
    async with ctx.db.sessions() as s:
        ch, u = await _load(s, job)
        p = registry.for_user(ctx, u)
        await budget.ensure(s, ctx, u, p)
        extra = job.payload.get("extra", "")
        if find_blocked(extra):
            raise JobFailed("content_blocked")
        prompt = prompts.appearance_prompt(ch.appearance, extra)
        batch = await _next_batch(s, ch, "candidate")
        res = await p.images.generate(prompt, job.payload.get("count", 8), *CANDIDATE_SIZE, seed=batch * 1000)
        budget.record(s, u.id, res.usage, ch.id)
        for data in res.images:
            await _store(ctx, s, ch, "candidate", data, prompt, batch)
        await s.commit()


async def choose(s: AsyncSession, ch: Character, image_id: int) -> Character:
    img = await s.get(CharacterImage, image_id)
    if img is None or img.character_id != ch.id or img.kind != "candidate" or img.deleted:
        raise CardError("image_not_found")
    ch.chosen_image_id = img.id
    ch.appearance_text = ""
    if ch.status in ("appearance", "refsheet"):
        ch.status = "refsheet"
    await s.flush()
    return ch


# step 3: reference sheet

async def request_refsheet(s: AsyncSession, ch: Character, count: int) -> Job | None:
    if not ch.chosen_image_id:
        raise CardError("choose_first")
    return await enqueue(s, "refsheet", ch.user_id, character_id=ch.id, payload={"count": max(MIN_REFS, min(20, count))},
                         dedupe_key=f"refsheet:{ch.id}")


@handler("refsheet")
async def gen_refsheet(ctx, job: Job) -> None:
    async with ctx.db.sessions() as s:
        ch, u = await _load(s, job)
        chosen = await s.get(CharacterImage, ch.chosen_image_id) if ch.chosen_image_id else None
        if chosen is None:
            raise JobFailed("choose_first")
        p = registry.for_user(ctx, u)
        await budget.ensure(s, ctx, u, p)
        src = await ctx.storage.get(chosen.key)
        # looks in words, for every future prompt
        if not ch.appearance_text:
            usages: list = []
            d = await ask_json(p.llm, "appearance_text", prompts.DESCRIBE_SYSTEM,
                               prompts.describe_content(src, ch.appearance), _Describe, usages.append)
            for x in usages:
                budget.record(s, u.id, x, ch.id)
            ch.appearance_text = d.appearance_text
            await s.commit()
        for old in await images(s, ch, "ref"):
            old.deleted = True
        batch = await _next_batch(s, ch, "ref")
        await s.commit()
        for i, variation in enumerate(prompts.REFSHEET_VARIATIONS[:job.payload.get("count", 16)]):
            await budget.ensure(s, ctx, u, p)
            prompt = prompts.refsheet_prompt(variation)
            res = await p.images.edit(src, prompt, seed=batch * 100 + i)
            budget.record(s, u.id, res.usage, ch.id)
            for data in res.images:
                await _store(ctx, s, ch, "ref", data, prompt, batch)
            await s.commit()  # refs appear one by one in the app


class _Describe(BaseModel):
    appearance_text: str = Field(min_length=10, max_length=600)


async def delete_image(s: AsyncSession, ch: Character, image_id: int) -> None:
    img = await s.get(CharacterImage, image_id)
    if img is None or img.character_id != ch.id:
        raise CardError("image_not_found")
    img.deleted = True
    await s.flush()


# step 4: training

async def request_training(s: AsyncSession, ch: Character) -> Job | None:
    refs = await images(s, ch, "ref")
    if len(refs) < MIN_REFS:
        raise CardError("not_enough_refs", [str(MIN_REFS)])
    if ch.status == "training":
        raise CardError("already_training")
    return await enqueue(s, "train", ch.user_id, character_id=ch.id, dedupe_key=f"train:{ch.id}")


@handler("train")
async def start_training(ctx, job: Job) -> None:
    async with ctx.db.sessions() as s:
        ch, u = await _load(s, job)
        p = registry.for_user(ctx, u)
        await budget.ensure(s, ctx, u, p)
        refs = await images(s, ch, "ref")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for i, img in enumerate(refs):
                z.writestr(f"{i:02d}.jpg", await ctx.storage.get(img.key))
                z.writestr(f"{i:02d}.txt", f"{ch.lora_trigger}, {ch.appearance_text or 'a cat'}")
        key = f"u{u.id}/c{ch.id}/training/{uuid.uuid4().hex}.zip"
        await ctx.storage.put(key, buf.getvalue(), "application/zip")
        if ctx.storage.public:
            zip_url = ctx.storage.url(key, 6 * 3600)
        else:
            from ..providers.fal import data_uri
            zip_url = data_uri(buf.getvalue(), "application/zip")
        handle, usage = await p.trainer.submit(zip_url, ch.lora_trigger)
        budget.record(s, u.id, usage, ch.id)
        handle["billed_to"] = p.trainer.billed_to
        ch.training, ch.training_error, ch.status, ch.lora_url = handle, None, "training", None
        await s.commit()


async def poll_trainings(ctx) -> int:
    """Worker step: check running trainings; when one is done, make test images."""
    done = 0
    async with ctx.db.sessions() as s:
        rows = (await s.execute(select(Character).where(Character.status == "training",
                                                        Character.archived.is_(False)))).scalars().all()
        for ch in rows:
            u = await s.get(User, ch.user_id)
            p = registry.for_user(ctx, u)
            st = await p.trainer.status(ch.training or {})
            if st.state == "done":
                ch.lora_url, ch.status = st.lora_url, "testing"
                for old in await images(s, ch, "test"):
                    old.deleted = True
                await enqueue(s, "test_images", u.id, character_id=ch.id, dedupe_key=f"test:{ch.id}")
                done += 1
            elif st.state == "failed":
                ch.status, ch.training_error = "refsheet", st.error or "training failed"
                await ctx.notifier.send(u.id, f"Обучение LoRA для <b>{ch.name}</b> не удалось: {ch.training_error}. "
                                              "Проверьте референсы и запустите ещё раз.", _web_app_button(ctx))
        await s.commit()
    return done


@handler("test_images")
async def gen_test_images(ctx, job: Job) -> None:
    async with ctx.db.sessions() as s:
        ch, u = await _load(s, job)
        p = registry.for_user(ctx, u)
        await budget.ensure(s, ctx, u, p)
        scenes = ["sitting on a windowsill, morning light", "walking across a living room rug, daylight",
                  "close-up portrait, soft studio light", "lying on a bed, evening lamp light"]
        batch = await _next_batch(s, ch, "test")
        for i, scene in enumerate(scenes):
            prompt = prompts.lora_prompt(ch.lora_trigger, ch.appearance_text, scene)
            res = await p.images.generate_lora(prompt, ch.lora_url, 1, *TEST_SIZE, seed=batch * 10 + i)
            budget.record(s, u.id, res.usage, ch.id)
            for data in res.images:
                await _store(ctx, s, ch, "test", data, prompt, batch)
        ch.status = "testing"
        await s.commit()
        await ctx.notifier.send(u.id, f"LoRA для <b>{ch.name}</b> обучена. Посмотрите 4 тестовые картинки и "
                                      "подтвердите, что это он.", _web_app_button(ctx, "Проверить"))


async def confirm(ctx, s: AsyncSession, ch: Character, ok: bool) -> Character:
    if ch.status != "testing":
        raise CardError("not_testing")
    if ok:
        ch.status = "ready"
        await s.flush()
        await ctx.notifier.send(ch.user_id, f"<b>{ch.name}</b> готов к постингу. Первый черновик придёт по "
                                            "расписанию, а в приложении можно сделать пост прямо сейчас.",
                                _web_app_button(ctx))
    else:
        ch.status = "refsheet"  # back to the references: remove bad ones and retrain
        await s.flush()
    return ch


async def on_fail_notify(ctx, job: Job, code: str) -> None:
    from .notify_texts import job_failed
    if code == "budget_exceeded":
        return  # budget.ensure already told the user
    await ctx.notifier.send(job.user_id, job_failed(job.kind, code), _web_app_button(ctx))


for _fn in (gen_candidates, gen_refsheet, start_training, gen_test_images):
    _fn.on_fail = on_fail_notify  # type: ignore[attr-defined]
