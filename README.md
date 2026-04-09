# Marketplace Report Bot — Railway-safe PostgreSQL build

This rewrite is designed for Railway deployment with PostgreSQL as the only database backend.

## What changed
- PostgreSQL-only persistence for Railway safety
- proper `%s` parameterized SQL and cursors
- UPSERTs rewritten for PostgreSQL
- scheduler and date logic use `Asia/Tashkent` timezone-aware helpers
- weekly and monthly reports now aggregate date ranges correctly
- Telegram output switched to HTML mode with escaping
- `/fetch` can be restricted via `ADMIN_USER_IDS`
- local junk removed from the deployable project
- Ozon HTTP sessions are reused instead of recreated on every request

## Railway setup
Create these Railway variables:
- `BOT_TOKEN`
- `GROUP_CHAT_ID`
- `DATABASE_URL`
- `OZON_A_CLIENT_ID`
- `OZON_A_API_KEY`
- `OZON_B_CLIENT_ID`
- `OZON_B_API_KEY`

Optional:
- `ADMIN_USER_IDS` — comma-separated Telegram user IDs allowed to run `/fetch`
- `TIMEZONE`
- scheduler and alert thresholds from `.env.example`

## Run locally
```bash
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env
python main.py
```

## Notes
- This package intentionally does **not** include `.env`, `.git`, `venv`, SQLite DB files, or CSV state dumps.
- Wildberries remains a stub.
- If your old tokens or keys were shared in the previous ZIP, rotate them.
