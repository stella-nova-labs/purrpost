from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """All settings come from environment variables (or backend/.env locally). No secrets in code."""

    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    # --- Telegram ---
    bot_token: str = ""
    webapp_url: str = ""  # public https URL of the Mini App (Railway service domain)
    # off: no bot (frontend work), polling: local test bot, webhook: production
    bot_mode: Literal["off", "polling", "webhook"] = "off"
    webhook_secret: str = ""
    owner_id: int = 0  # the owner: full access, admin panel, invite codes
    admin_ids: str = ""  # extra admins, comma separated
    init_data_max_age: int = 86400

    # --- Database ---
    database_url: str = f"sqlite+aiosqlite:///{(BACKEND_DIR / 'data' / 'dev.db').as_posix()}"
    auto_create_schema: bool = False  # local SQLite only; production uses alembic upgrade head

    # --- Local development ---
    dev_auth: bool = False  # accept `Authorization: tma dev:<id>` without a signature (LOCAL ONLY)
    dev_fake_providers: bool = False  # fake LLM / images / LoRA / publishers, no keys needed
    # Run the worker loop inside the web process (handy locally; on Railway a separate worker service runs it)
    run_worker: bool = False
    worker_interval_sec: int = 20

    # --- Encryption of user tokens and keys (Fernet key, base64, 32 bytes) ---
    encryption_key: str = ""

    # --- Anthropic ---
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5-5"
    anthropic_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    # USD per million tokens, for the usage estimate
    anthropic_price_in: float = 4.0
    anthropic_price_out: float = 20.0
    # Server-side refusal fallback (Claude API only). Turn off if your platform rejects it.
    anthropic_fallbacks: bool = True

    # --- fal.ai ---
    fal_key: str = ""
    fal_model_candidates: str = "fal-ai/flux/dev"
    fal_model_edit: str = "fal-ai/flux-pro/kontext"
    fal_model_lora: str = "fal-ai/flux-lora"
    fal_model_training: str = "fal-ai/flux-lora-fast-training"
    fal_training_steps: int = 1000

    # --- Storage (S3-compatible: Railway bucket) ---
    s3_endpoint: str = ""
    s3_bucket: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "auto"
    s3_url_style: Literal["virtual", "path"] = "virtual"  # Railway shows it in the bucket's credentials
    s3_public_base_url: str = ""  # if the bucket is public; otherwise presigned URLs are used
    presign_ttl_sec: int = 3600
    media_dir: str = str(BACKEND_DIR / "data" / "media")  # local storage when S3 is not configured

    # --- Meta (Instagram API with Instagram Login) and Threads ---
    meta_app_id: str = ""
    meta_app_secret: str = ""
    meta_graph_version: str = "v23.0"
    threads_app_id: str = ""
    threads_app_secret: str = ""
    # Public base URL for OAuth callbacks; defaults to webapp_url
    public_base_url: str = ""

    # --- Business rules ---
    default_budget_usd: float = 15.0
    autopilot_streak: int = 10
    timezone: str = "Europe/Moscow"  # owner's time zone for monthly budgets

    @property
    def db_url(self) -> str:
        url = self.database_url
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+asyncpg://" + url[len(prefix):]
        return url

    @property
    def admin_id_set(self) -> set[int]:
        ids = {int(x) for x in self.admin_ids.replace(" ", "").split(",") if x}
        if self.owner_id:
            ids.add(self.owner_id)
        return ids

    @property
    def base_url(self) -> str:
        return (self.public_base_url or self.webapp_url or "http://localhost:8000").rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()
