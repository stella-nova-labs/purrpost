"""Everything a request handler, the bot or the worker needs: settings, DB, storage, notifier, providers.

One object, built once per process. Tests build it with fakes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import Settings
from .db import Database


@dataclass
class Ctx:
    settings: Settings
    db: Database
    storage: Any  # providers.base.Storage
    notifier: Any = None  # services.notify.Notifier
    bot: Any = None  # aiogram Bot or None
    http: httpx.AsyncClient = field(default_factory=lambda: httpx.AsyncClient(timeout=60.0))
    # Fake providers (DEV_FAKE_PROVIDERS=1): shared instances so tests can script their answers
    fakes: dict = field(default_factory=dict)
    # Publishers by platform (filled in by the publishing phase); tests swap them for fakes
    publishers: dict = field(default_factory=dict)
    bot_username: str | None = None
