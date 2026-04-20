import asyncio
import logging
import os
import threading

from dotenv import load_dotenv
from fastapi import FastAPI
import uvicorn

load_dotenv(".env")

from app.bot import GatewayBot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-18s  %(levelname)-7s  %(message)s",
)
logger = logging.getLogger("gateway-app")

ENVIRONMENT = os.getenv("ENVIRONMENT", "production")

if ENVIRONMENT == "development":
    DISCORD_BOT_TOKEN = os.getenv("DISCORD_DEV_BOT_TOKEN", "")
else:
    DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")

AI_GATEWAY_URL = os.getenv("AI_GATEWAY_URL", "http://127.0.0.1:8080/process-command").strip()

STATUS_SERVER_PORT = int(os.getenv("STATUS_SERVER_PORT", "8443"))

app = FastAPI()


@app.get("/")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


def run_status_server() -> None:
    logger.info("Starting status server on port %d", STATUS_SERVER_PORT)
    uvicorn.run(app, host="0.0.0.0", port=STATUS_SERVER_PORT, log_level="info")


async def main() -> None:
    if not DISCORD_BOT_TOKEN:
        raise SystemExit("ERROR: DISCORD_BOT_TOKEN or DISCORD_DEV_BOT_TOKEN must be set")
    if not AI_GATEWAY_URL:
        raise SystemExit("ERROR: AI_GATEWAY_URL must be set")

    status_thread = threading.Thread(target=run_status_server, daemon=True)
    status_thread.start()
    logger.info("Status server thread started")

    bot = GatewayBot(DISCORD_BOT_TOKEN)
    logger.info("Starting Discord gateway bot")
    await bot.start()


if __name__ == "__main__":
    asyncio.run(main())