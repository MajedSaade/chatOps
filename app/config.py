"""
config.py — Environment-variable loading & validation.

Reads required Discord credentials and optional config from a .env file
(via python-dotenv) or from actual environment variables.
"""

import os
import sys

from dotenv import load_dotenv

# Load .env file from the project root (one level up from app/)
load_dotenv()

# ── Required variables ──────────────────────────────────────────────
DISCORD_BOT_TOKEN: str = os.getenv("DISCORD_BOT_TOKEN", "")

_REQUIRED = {
    "DISCORD_BOT_TOKEN": DISCORD_BOT_TOKEN,
}

_missing = [name for name, value in _REQUIRED.items() if not value]
if _missing:
    print(
        f"[config] ERROR — missing required env vars: {', '.join(_missing)}. "
        "Copy .env.example → .env and fill in the values.",
        file=sys.stderr,
    )

# ── Optional variables ──────────────────────────────────────────────
KUBE_NAMESPACE: str = os.getenv("KUBE_NAMESPACE", "default")

# Self-hosted LLM agent endpoint
LLM_AGENT_URL: str = os.getenv("LLM_AGENT_URL", "http://localhost:11434")
LLM_AGENT_TIMEOUT: int = int(os.getenv("LLM_AGENT_TIMEOUT", "120"))
