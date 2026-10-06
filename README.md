# Telegram To-Do & Reminder Bot

A personal productivity bot for Telegram. Capture tasks, set reminders, and stay on top of your day — without leaving Telegram.

---

## Features (MVP)

- ✅ **Create tasks** with a guided step-by-step flow
- ⏰ **Reminders** delivered at the exact scheduled time
- 📋 **View** today's tasks and upcoming tasks (next 7 days)
- ✏️ **Edit** and 🗑️ **delete** tasks anytime
- 😴 **Snooze** reminders by 10 or 30 minutes
- 📅 **Daily morning summary** at 08:00

---

## Quick Start

### 1. Clone and set up environment

```bash
git clone <your-repo-url>
cd telegram-todo-bot

# Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux
```

### 2. Install dependencies

```bash
pip install -r requirements-dev.txt
```

### 3. Configure environment variables

```bash
copy .env.example .env          # Windows
# cp .env.example .env          # macOS/Linux
```

Edit `.env` and fill in your **Telegram bot token** from [@BotFather](https://t.me/BotFather):

```env
TELEGRAM_BOT_TOKEN=your_actual_token_here
DATABASE_URL=sqlite:///./todo_bot.db
BOT_MODE=polling
TIMEZONE=Asia/Kolkata
LOG_LEVEL=INFO
```

### 4. Run the bot

```bash
python -m bot.main
```

The bot will:
1. Create the SQLite database file automatically
2. Start polling for Telegram messages
3. Respond to `/start` and `/help`

---

## Running Tests

```bash
pytest tests/ -v
```

Tests use an **in-memory SQLite database** — no `.db` file is created.

---

## Project Structure

```
bot/
├── config.py          — All settings (loaded from .env)
├── main.py            — Entry point
├── handlers/          — Telegram command handlers (thin layer)
├── services/          — Business logic (no Telegram imports)
├── scheduler/         — APScheduler jobs
├── database/          — SQLAlchemy models + session factory
└── utils/             — Helpers: messages, keyboards, datetime

tests/                 — pytest unit + integration tests
alembic/               — Database migration scripts
```

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ Yes | — | Token from @BotFather |
| `DATABASE_URL` | No | `sqlite:///./todo_bot.db` | SQLAlchemy connection string |
| `BOT_MODE` | No | `polling` | `polling` or `webhook` |
| `WEBHOOK_URL` | Webhook only | — | Public HTTPS URL for webhook |
| `WEBHOOK_PORT` | No | `8443` | Webhook listen port |
| `TIMEZONE` | No | `Asia/Kolkata` | Default timezone (IANA format) |
| `LOG_LEVEL` | No | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |

---

## Database Migrations (Alembic)

```bash
# Apply all pending migrations
alembic upgrade head

# Generate a new migration after model changes
alembic revision --autogenerate -m "description of change"

# Roll back one step
alembic downgrade -1
```

> **Note:** For local development, `python -m bot.main` automatically creates all tables via `init_db()`. Use Alembic for production deployments.

---

## Commands

| Command | Description |
|---|---|
| `/start` | Welcome message + onboarding |
| `/help` | Show all commands |
| `/add` | Create a new task (guided flow) |
| `/today` | View today's tasks |
| `/upcoming` | View next 7 days |
| `/done` | Mark a task complete |
| `/edit` | Edit an existing task |
| `/delete` | Delete a task |
| `/settings` | Change timezone preference |
| `/cancel` | Cancel current action |

---

## Development Phases

| Phase | Status | Scope |
|---|---|---|
| 1 | ✅ Done | Project skeleton, DB models, `/start` `/help` |
| 2 | ⬜ Next | Task creation (`/add` conversational flow) |
| 3 | ⬜ | Task listing (`/today`, `/upcoming`) |
| 4 | ⬜ | Task actions (`/done`, `/edit`, `/delete`) |
| 5 | ⬜ | Reminder scheduler + notifications |
| 6 | ⬜ | Snooze + daily morning summary |
| 7 | ⬜ | `/settings` + timezone management |
| 8 | ⬜ | Tests, logging, error handling |
| 9 | ⬜ | Production deployment |

---

## Security Notes

- **Never commit `.env`** — it is listed in `.gitignore`
- Bot token is loaded from environment variables only — never hardcoded
- User ownership is validated before any task modification
- HTTPS used for all Telegram API communication

---

## License

MIT
