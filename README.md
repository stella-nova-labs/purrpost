# Purrpost

Telegram Mini App that runs Instagram accounts of AI characters (cats): stable looks via a per-character LoRA, daily posts in character, carousel images, scheduled publishing. A human approves drafts with one tap, or turns on autopilot.

Work in progress: full setup and deployment docs come in the last phase.

## Local run (no keys)

```bash
cd backend && uv venv -p 3.12 .venv && uv pip install -p .venv/bin/python -r requirements-dev.txt
DEV_AUTH=1 DEV_FAKE_PROVIDERS=1 AUTO_CREATE_SCHEMA=1 RUN_WORKER=1 OWNER_ID=1 .venv/bin/uvicorn app.main:app --reload --port 8000
cd ../frontend && npm ci && npm run dev   # http://localhost:5173/?dev=1  (owner), ?dev=2 (a friend without an invite)
```

Tests: `cd backend && .venv/bin/pytest -q`; frontend: `npx oxlint && npm run build`.
