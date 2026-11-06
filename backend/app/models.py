"""Tables. All timestamps are Unix milliseconds (`*_ms`)."""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
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


