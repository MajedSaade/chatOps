# Discord Gateway ChatOps Bot

A gateway-based Discord bot with:

- Slash commands for Kubernetes and AWS checks
- Message relay to an external AI gateway service
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
- `AI_GATEWAY_URL` (optional, default `http://127.0.0.1:8080/process-command` for local runs)
- `AI_GATEWAY_TIMEOUT_SECONDS` (optional, default `30`)

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
    ├── bot.py        # Class-based Discord gateway relay bot
    ├── commands.py   # K8s and AWS command handlers
    └── config.py     # Environment loading and config
```

## Notes

- The bot relays non-command messages to `AI_GATEWAY_URL` and returns gateway text responses.
- Kubernetes and AWS credentials must be available in the runtime environment.

## Docker

### Build and run locally

```bash
docker build -t discordapp:local .
docker run --rm -p 8443:8443 --env-file .env discordapp:local
```

### GitHub Actions container deployment

This repository now uses:

- `.github/workflows/build-app.yaml` to build and push an image to Docker Hub
- `.github/workflows/deploy-app.yaml` to deploy that image on EC2 using Docker Compose

Required GitHub secrets:

- `DOCKERHUB_USERNAME`
- `DOCKERHUB_TOKEN`
- `EC2_SSH_KEY`
- `EC2_HOST`
- `EC2_USERNAME`
- `DISCORD_BOT_TOKEN`

Optional GitHub variables:

- `DOCKERHUB_REPOSITORY` (default: `discordapp`)
- `KUBE_NAMESPACE` (default: `default`)
- `AI_GATEWAY_URL` (optional; if unset, deploy defaults to `http://host.docker.internal:8080/process-command`)
- `AI_GATEWAY_TIMEOUT_SECONDS` (default: `30`)
- `STATUS_SERVER_PORT` (default: `8443`)
