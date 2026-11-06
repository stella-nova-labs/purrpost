"""Tables. All timestamps are Unix milliseconds (`*_ms`)."""

from __future__ import annotations

from sqlalchemy import JSON, BigInteger, Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Telegram user id
    first_name: Mapped[str] = mapped_column(String(128), default="")
    username: Mapped[str | None] = mapped_column(String(64))
    language: Mapped[str | None] = mapped_column(String(8))
    # Access: the owner always, everyone else after redeeming an invite code
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    invite_code: Mapped[str | None] = mapped_column(String(32))
    budget_usd: Mapped[float] = mapped_column(Float, default=15.0)
    created_ms: Mapped[int] = mapped_column(BigInteger, default=0)
    last_seen_ms: Mapped[int] = mapped_column(BigInteger, default=0)
    # The user's own provider keys (Fernet-encrypted, never sent to the client). With a key the
    # matching usage is billed to the user's own account, not to the shared budget.
    fal_key_enc: Mapped[str | None] = mapped_column(Text)
    anthropic_key_enc: Mapped[str | None] = mapped_column(Text)
    # "YYYY-MM" of the last "budget exhausted" bot message, so it is sent once a month
    budget_notified_month: Mapped[str | None] = mapped_column(String(7))


class InviteCode(Base):
    __tablename__ = "invite_codes"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    max_uses: Mapped[int] = mapped_column(Integer, default=1)
    uses: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str] = mapped_column(String(200), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int] = mapped_column(BigInteger, default=0)
    created_ms: Mapped[int] = mapped_column(BigInteger, default=0)


class InviteRedemption(Base):
    __tablename__ = "invite_redemptions"
    __table_args__ = (UniqueConstraint("user_id", name="uq_redemption_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(ForeignKey("invite_codes.code"))
    user_id: Mapped[int] = mapped_column(BigInteger)
    created_ms: Mapped[int] = mapped_column(BigInteger, default=0)




class Usage(Base):
    """One paid operation with its estimated cost (provider tariff)."""

    __tablename__ = "usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    character_id: Mapped[int | None] = mapped_column(Integer, index=True)
    provider: Mapped[str] = mapped_column(String(32))  # anthropic | fal
    kind: Mapped[str] = mapped_column(String(48))  # llm.post_plan, image.lora, lora.training, ...
    units: Mapped[float] = mapped_column(Float, default=0)  # tokens, images, megapixels, runs
    cost_usd: Mapped[float] = mapped_column(Float, default=0)
    billed_to: Mapped[str] = mapped_column(String(8), default="shared")  # shared | own
    created_ms: Mapped[int] = mapped_column(BigInteger, index=True, default=0)


class Character(Base):
    """An AI character and its "bible": personality, rubrics, looks in words, LoRA and story so far."""

    __tablename__ = "characters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    template_slug: Mapped[str | None] = mapped_column(String(32))
    # --- step 1: character ---
    name: Mapped[str] = mapped_column(String(80))
    handle: Mapped[str] = mapped_column(String(40))
    personality: Mapped[str] = mapped_column(Text, default="")
    pain: Mapped[str] = mapped_column(Text, default="")
    humor: Mapped[str] = mapped_column(String(200), default="")
    language: Mapped[str] = mapped_column(String(8), default="en")
    rubrics: Mapped[list] = mapped_column(JSON, default=list)  # [{weekday: 0-6|null, title, description}]
    stop_topics: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")
    # --- step 2-3: looks ---
    appearance: Mapped[dict] = mapped_column(JSON, default=dict)  # {breed, color, marks, signature}
    appearance_text: Mapped[str] = mapped_column(Text, default="")  # words for image prompts
    chosen_image_id: Mapped[int | None] = mapped_column(Integer)
    # --- step 4-5: LoRA ---
    lora_trigger: Mapped[str] = mapped_column(String(48), default="")
    lora_url: Mapped[str | None] = mapped_column(Text)
    training: Mapped[dict | None] = mapped_column(JSON)  # provider handle while training
    training_error: Mapped[str | None] = mapped_column(Text)
    # draft -> appearance -> refsheet -> training -> testing -> ready
    status: Mapped[str] = mapped_column(String(16), default="appearance")
    # --- posting ---
    schedule: Mapped[dict] = mapped_column(JSON, default=dict)  # {times: ["18:00"], days: [0..6], tz, lead_hours}
    slides_max: Mapped[int] = mapped_column(Integer, default=5)
    autopilot: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_streak: Mapped[int] = mapped_column(Integer, default=0)
    ai_disclosure: Mapped[bool] = mapped_column(Boolean, default=True)
    disclosure_text: Mapped[str] = mapped_column(String(80), default="🤖 AI character")
    trend: Mapped[str] = mapped_column(Text, default="")  # a trend the user typed in, used in the next posts
    lore: Mapped[list] = mapped_column(JSON, default=list)  # last 30 posts: [{date, rubric, summary}]
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_ms: Mapped[int] = mapped_column(BigInteger, default=0)


class CharacterImage(Base):
    __tablename__ = "character_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id"), index=True)
    kind: Mapped[str] = mapped_column(String(12))  # candidate | ref | test
    key: Mapped[str] = mapped_column(String(200))
    prompt: Mapped[str] = mapped_column(Text, default="")
    batch: Mapped[int] = mapped_column(Integer, default=1)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_ms: Mapped[int] = mapped_column(BigInteger, default=0)


class Job(Base):
    """Background task queue (generation, training, publishing). The worker claims jobs atomically."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    character_id: Mapped[int | None] = mapped_column(Integer, index=True)
    draft_id: Mapped[int | None] = mapped_column(Integer, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    # Same key twice -> one job (e.g. "plan:<draft id>")
    dedupe_key: Mapped[str | None] = mapped_column(String(80), unique=True)
    status: Mapped[str] = mapped_column(String(12), default="queued", index=True)  # queued|running|done|failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    run_after_ms: Mapped[int] = mapped_column(BigInteger, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_ms: Mapped[int] = mapped_column(BigInteger, default=0)
    finished_ms: Mapped[int | None] = mapped_column(BigInteger)
