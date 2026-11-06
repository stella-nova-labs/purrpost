"""Local media (development storage). In production images live in the S3 bucket."""

from __future__ import annotations

import mimetypes

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

router = APIRouter()


@router.get("/media/{key:path}", include_in_schema=False)
async def media(key: str, exp: int, sig: str, request: Request) -> Response:
    storage = request.app.state.ctx.storage
    if not hasattr(storage, "check") or not storage.check(key, exp, sig):
        raise HTTPException(403)
    try:
        data = await storage.get(key)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(404) from e
    return Response(data, media_type=mimetypes.guess_type(key)[0] or "application/octet-stream",
                    headers={"Cache-Control": "private, max-age=86400"})
