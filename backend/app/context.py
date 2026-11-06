"""Everything a request handler, the bot or the worker needs: settings, DB, storage, notifier, providers.

One object, built once per process. Tests build it with fakes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import Settings
from .db import Database


@dataclass
class Ctx:
    settings: Settings
    db: Database
    notifier: Any = None  # services.notify.Notifier
    bot: Any = None  # aiogram Bot or None
    extra: dict = field(default_factory=dict)
