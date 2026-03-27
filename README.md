# SenteCheck

> Track your betting finances automatically — built for young Ugandan bettors.

SenteCheck reads your MTN and Airtel Mobile Money SMS in the background, identifies bet deposits and withdrawals, and sends you a Telegram message asking you to confirm what each payment was for. From there you get dashboards, P&L summaries, win/loss tracking, and a bankroll health monitor — all in Telegram.

---

## Architecture

```
Android app  ──SMS──►  FastAPI backend  ──updates──►  Telegram Bot
(BroadcastReceiver)     (Railway.app)                  (@your_bot)
                             │
                        PostgreSQL 15
                      (Railway managed)
```

1. The Android app intercepts incoming mobile money SMS and forwards them (over HTTPS) to the FastAPI backend.
2. The backend parses each SMS, looks up the merchant, and either auto-classifies it or prompts you via Telegram.
3. You tap a button in Telegram to confirm whether a payment was a bet deposit, bet withdrawal, or something else.
4. Bot commands (`/summary`, `/losses`, `/wins`, `/history`, `/bankroll`) give you real-time insight.

---

## Quickstart — Backend (local dev)

### Prerequisites

- Python 3.11+
- PostgreSQL 15+ (or use Railway's managed Postgres)
- A Telegram bot token from [@BotFather](https://t.me/BotFather)

### 1. Clone and install

```bash
git clone <repo-url>
cd SenteCheck
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in all six values:

| Variable | How to get it |
|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://user:pass@localhost:5432/sentecheck` |
| `TELEGRAM_BOT_TOKEN` | From [@BotFather](https://t.me/BotFather) — `/newbot` |
| `WEBHOOK_SECRET` | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `FASTAPI_BASE_URL` | Your public HTTPS URL (ngrok for local dev) |
| `ENCRYPTION_KEY` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `ENVIRONMENT` | `development` locally, `production` on Railway |

### 3. Run migrations

```bash
alembic upgrade head
```

### 4. Start the server

```bash
uvicorn app.main:app --reload
```

On startup, the server registers its Telegram webhook automatically using `FASTAPI_BASE_URL`.

For local development, expose your server with [ngrok](https://ngrok.com):

```bash
ngrok http 8000
# Copy the https URL → set as FASTAPI_BASE_URL in .env → restart uvicorn
```

### 5. Run tests

```bash
pytest
```

All tests use an in-memory SQLite database — no external services required.

---

## Deploy to Railway

### One-time setup

1. Create a new Railway project.
2. Add a **PostgreSQL** service inside the project. Railway sets `DATABASE_URL` automatically — but note Railway uses a plain `postgresql://` URL; you must override it in your service variables with the `asyncpg` variant:

   ```
   DATABASE_URL=postgresql+asyncpg://<rest of the Railway DATABASE_URL>
   ```

3. Add a new **service** from this repo (connect GitHub or push directly).
4. Set all six environment variables from `.env.example` in the Railway service settings. `FASTAPI_BASE_URL` should be your Railway-generated domain (e.g. `https://sentecheck-api-production.up.railway.app`).
5. Railway will build the `Dockerfile` and run migrations automatically on every deploy.

### Re-deploys

Push to `main` → Railway rebuilds → `alembic upgrade head` runs → app restarts. Zero-downtime if you use Railway's rolling deploys.

---

## Quickstart — Android app

1. Open the `android/` folder in Android Studio.
2. In `android/app/build.gradle`, set `buildConfigField` `API_BASE_URL` to your Railway URL (already set to a placeholder — change it before building).
3. Build and install the APK on your Android phone (minSdk 26 / Android 8+).
4. Open the app:
   - Grant SMS permissions when prompted.
   - Enter your **Telegram User ID** (send `/start` to your bot in Telegram — the bot will display your ID after you agree to the consent form).
   - Enter the **Webhook Secret** (same value as `WEBHOOK_SECRET` in your `.env`).
   - Tap **Save & Connect**.
5. The app now runs silently in the background. Every incoming MTN or Airtel Mobile Money SMS is forwarded to the backend. Personal SMS are never forwarded.

---

## Bot commands

| Command | Description |
|---|---|
| `/start` | Register and give consent (required before first use) |
| `/summary` | Full P&L: deposits, withdrawals, net, win rate |
| `/losses` | Loss dashboard with biggest loss and recent history |
| `/wins` | Win dashboard with total profit |
| `/history [n]` | Last *n* transactions (default 10, max 50) |
| `/bankroll set [amount]` | Set your monthly betting budget |
| `/bankroll status` | Bankroll health, % used, recommended stake |
| `/bet [stake] [win/loss/pending] [return]` | Manually log a bet outcome |
| `/merchants` | List all classified merchants |
| `/addmerchant [NAME] [bet/other]` | Manually classify a merchant |
| `/mydata` | View everything stored about you |
| `/deleteaccount` | Permanently delete your account and all data |
| `/help` | Show command list |

---

## Privacy

SenteCheck operates under Uganda's **Data Protection and Privacy Act 2019**.

- The Android app only forwards SMS containing mobile money keywords (`UGX`, `MTN Mobile Money`, `Airtel Money`, etc.). Personal messages never leave the device.
- Raw SMS text is encrypted at rest using AES-128 Fernet encryption.
- All data transfer uses HTTPS.
- You can view everything stored about you with `/mydata` and delete it all permanently with `/deleteaccount`.
- Consent is recorded with a timestamp and version number.

---

## Project structure

```
SenteCheck/
├── app/
│   ├── bot/            # Telegram bot (PTB v20): handlers, keyboards, setup
│   ├── models/         # SQLAlchemy ORM models
│   ├── routers/        # FastAPI routers (webhook endpoints)
│   ├── schemas/        # Pydantic request/response schemas
│   ├── services/       # Business logic (parser, dashboard, merchants, users)
│   └── utils/          # Rate limiter, Fernet encryption TypeDecorator
├── alembic/            # Database migration scripts
├── tests/              # pytest test suite (SQLite in-memory)
├── android/            # Android app (Kotlin)
├── Dockerfile
├── railway.toml
└── .env.example
```
