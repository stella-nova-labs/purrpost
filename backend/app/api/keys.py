"""The user's own provider keys. Stored encrypted; the API only says whether a key is set."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..services.crypto import decrypt, encrypt, mask
from .deps import ActiveUser, Session, SettingsDep

router = APIRouter(prefix="/api/me")


def keys_out(u, settings) -> dict:
    return {"fal": mask(decrypt(settings, u.fal_key_enc)), "anthropic": mask(decrypt(settings, u.anthropic_key_enc))}


class KeysIn(BaseModel):
    # None: leave as is, "": remove, value: set
    fal: str | None = Field(None, max_length=300)
    anthropic: str | None = Field(None, max_length=300)


@router.get("/keys")
async def get_keys(u: ActiveUser, settings: SettingsDep) -> dict:
    return keys_out(u, settings)


@router.put("/keys")
async def put_keys(body: KeysIn, u: ActiveUser, s: Session, settings: SettingsDep) -> dict:
    if body.fal is not None:
        u.fal_key_enc = encrypt(settings, body.fal.strip()) if body.fal.strip() else None
    if body.anthropic is not None:
        u.anthropic_key_enc = encrypt(settings, body.anthropic.strip()) if body.anthropic.strip() else None
    await s.commit()
    return keys_out(u, settings)
