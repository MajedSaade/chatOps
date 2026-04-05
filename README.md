# Discord Gateway ChatOps Bot

A gateway-based Discord bot with:

- Slash commands for Kubernetes and AWS checks
- Automatic chat replies in server channels and DMs
- A lightweight FastAPI status endpoint

## Quick Start

### 1. Install dependencies

```bash
cd DiscordApp
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

Create `.env` and set:

- `DISCORD_BOT_TOKEN` (required)
- `KUBE_NAMESPACE` (optional, default: `default`)

### 3. Configure environment

Set these values in `.env`:

- `DISCORD_BOT_TOKEN` (required in production)
- `DISCORD_DEV_BOT_TOKEN` (used when `ENVIRONMENT=development`)
- `ENVIRONMENT` (`production` or `development`)
- `STATUS_SERVER_PORT` (optional, default `8443`)
- `KUBE_NAMESPACE` (optional, default `default`)

### 4. Run the app

```bash
python -m app.app
```

This starts:

- The Discord gateway bot
- The status server (`GET /` returns `{"status": "ok"}`)

## Project Structure

```
DiscordApp/
├── requirements.txt
├── README.md
└── app/
    ├── __init__.py
    ├── app.py        # Main entrypoint and status server
    ├── bot.py        # Class-based Discord gateway bot
    ├── chat.py       # Conversational message responses
    ├── commands.py   # K8s and AWS command handlers
    └── config.py     # Environment loading and config
```

## Notes

- The bot replies to non-bot messages without requiring a mention.
- Kubernetes and AWS credentials must be available in the runtime environment.
