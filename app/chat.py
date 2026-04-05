"""
chat.py — Conversational message handler for the Discord gateway bot.

Handles regular text messages (DMs and mentions) with friendly,
natural responses using simple pattern matching.
"""

import random
import re
import os
import asyncio

import aiohttp

# ── Ollama defaults ──────────────────────────────────────────────────
DEFAULT_OLLAMA_MODEL = "llama3"
DEFAULT_OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
DEFAULT_OLLAMA_TIMEOUT_SECONDS = 60


class OllamaError(Exception):
    """Raised when the local Ollama chat request fails."""


def _get_ollama_settings() -> tuple[str, str, int]:
    """Load Ollama settings from environment at request time."""
    model = os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
    chat_url = os.getenv("OLLAMA_CHAT_URL", DEFAULT_OLLAMA_CHAT_URL)
    timeout_seconds = int(
        os.getenv("OLLAMA_TIMEOUT_SECONDS", str(DEFAULT_OLLAMA_TIMEOUT_SECONDS))
    )
    return model, chat_url, timeout_seconds


async def ask_ollama(prompt: str) -> str:
    """Send a prompt to the local Ollama chat endpoint and return generated text."""
    model, chat_url, timeout_seconds = _get_ollama_settings()

    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
    }

    timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(chat_url, json=payload) as response:
                if response.status >= 400:
                    error_body = await response.text()
                    raise OllamaError(
                        f"Ollama returned HTTP {response.status}: {error_body[:300]}"
                    )

                data = await response.json()
                message = data.get("message", {})
                content = message.get("content", "").strip()
                if not content:
                    raise OllamaError("Ollama returned an empty response")

                return content
    except (aiohttp.ClientError, aiohttp.ContentTypeError, asyncio.TimeoutError) as exc:
        raise OllamaError("Could not connect to local Ollama") from exc

# ── Response patterns ────────────────────────────────────────────────
# Each entry: (compiled regex, list of possible responses)
# Patterns are checked in order; first match wins.

_PATTERNS: list[tuple[re.Pattern, list[str]]] = [
    # ── Greetings ────────────────────────────────────────────────────
    (
        re.compile(
            r"\b(hi|hello|hey|howdy|yo|sup|hiya|greetings|salut|what'?s\s*up)\b",
            re.IGNORECASE,
        ),
        [
            "Hey there! 👋 How can I help you today?",
            "Hello! 😊 What's on your mind?",
            "Hi! Great to see you! What can I do for you?",
            "Hey! 👋 I'm here if you need anything!",
            "Howdy! What brings you here today?",
        ],
    ),
    # ── How are you ──────────────────────────────────────────────────
    (
        re.compile(
            r"\bhow\s+(are\s+you|r\s*u|are\s+ya|you\s+doing|do\s+you\s+do)\b",
            re.IGNORECASE,
        ),
        [
            "I'm doing great, thanks for asking! 😄 How about you?",
            "Running smoothly! ⚡ How are you doing?",
            "All systems operational! 🟢 How's your day going?",
            "I'm fantastic, thanks! What can I help you with?",
            "Doing awesome! 🚀 What about you?",
        ],
    ),
    # ── What are you / who are you ───────────────────────────────────
    (
        re.compile(
            r"\b(what|who)\s+(are\s+you|r\s*u)\b",
            re.IGNORECASE,
        ),
        [
            "I'm your friendly ChatOps bot! 🤖 I can help with cluster health, logs, and AWS costs. Try my slash commands!",
            "I'm a DevOps assistant bot! I handle K8s queries, log fetching, and AWS cost reports. 💼",
            "I'm your infrastructure buddy! Use `/cluster-health`, `/logs`, or `/aws-cost` to put me to work! 🔧",
        ],
    ),
    # ── What can you do ──────────────────────────────────────────────
    (
        re.compile(
            r"\b(what\s+(can|do)\s+you\s+do|help|commands?)\b",
            re.IGNORECASE,
        ),
        [
            (
                "Here's what I can do:\n"
                "🟢 `/cluster-health` — Check pod status\n"
                "📋 `/logs <pod>` — Fetch pod logs\n"
                "💰 `/aws-cost` — Month-to-date AWS bill\n\n"
                "Or just chat with me! I'm happy to talk 😊"
            ),
        ],
    ),
    # ── Thanks ───────────────────────────────────────────────────────
    (
        re.compile(
            r"\b(thanks?|thank\s*you|thx|ty|cheers)\b",
            re.IGNORECASE,
        ),
        [
            "You're welcome! 😊",
            "Anytime! Happy to help! 🎉",
            "No problem at all! Let me know if you need anything else.",
            "Glad I could help! 👍",
            "My pleasure! ✨",
        ],
    ),
    # ── Goodbye ──────────────────────────────────────────────────────
    (
        re.compile(
            r"\b(bye|goodbye|see\s*ya|later|cya|good\s*night|gn)\b",
            re.IGNORECASE,
        ),
        [
            "See you later! 👋",
            "Goodbye! Have a great day! 🌟",
            "Catch you later! Take care! 😊",
            "Bye! I'll be here whenever you need me! 💙",
        ],
    ),
    # ── Good morning / afternoon / evening ───────────────────────────
    (
        re.compile(
            r"\bgood\s*(morning|afternoon|evening|day)\b",
            re.IGNORECASE,
        ),
        [
            "Good {0}! ☀️ How can I help you today?",
            "Good {0}! Hope you're having a great one! 😊",
            "Good {0}! What can I do for you? 🚀",
        ],
    ),
    # ── Bot status ───────────────────────────────────────────────────
    (
        re.compile(
            r"\b(you\s+alive|you\s+there|ping|status|you\s+up)\b",
            re.IGNORECASE,
        ),
        [
            "I'm here! 🟢 All systems go!",
            "Alive and kicking! ⚡ What do you need?",
            "Pong! 🏓 I'm online and ready!",
            "Yep, I'm here! How can I help?",
        ],
    ),
    # ── Compliments ──────────────────────────────────────────────────
    (
        re.compile(
            r"\b(you('re|\s+are)\s+(awesome|great|cool|amazing|the\s+best|wonderful))\b",
            re.IGNORECASE,
        ),
        [
            "Aww, thanks! You're pretty awesome yourself! 😊",
            "That means a lot! 💙 Thank you!",
            "You're making me blush! 😄 Thanks!",
        ],
    ),
    # ── Jokes ────────────────────────────────────────────────────────
    (
        re.compile(
            r"\b(tell\s+me\s+a\s+joke|joke|make\s+me\s+laugh|funny)\b",
            re.IGNORECASE,
        ),
        [
            "Why do programmers prefer dark mode? Because light attracts bugs! 🐛",
            "Why did the DevOps engineer break up? Too many unresolved issues! 💔",
            "What's a pod's favorite music? K8s-pop! 🎵",
            "Why did the container go to therapy? It had too many issues with its image! 🐳",
            "I'd tell you a UDP joke, but you might not get it. 📡",
        ],
    ),
]

# ── Fallback responses ───────────────────────────────────────────────
_FALLBACKS = [
    "Hmm, I'm not sure how to respond to that 🤔 Try asking me something else, or use `/help` for my commands!",
    "Interesting! I'm still learning new things. Try `/cluster-health`, `/logs`, or `/aws-cost` for infra queries! 🔧",
    "I didn't quite catch that, but I'm here to help! What do you need? 😊",
    "Not sure about that one! But I'm great at DevOps stuff — try my slash commands! 🚀",
]


def get_response(message_content: str) -> str:
    """
    Match the incoming message against known patterns and return
    a random response from the matched category.

    Falls back to a generic response if no pattern matches.
    """
    for pattern, responses in _PATTERNS:
        match = pattern.search(message_content)
        if match:
            response = random.choice(responses)
            # Support {0}, {1}, … placeholders filled from capture groups
            if match.groups():
                try:
                    response = response.format(*match.groups())
                except (IndexError, KeyError):
                    pass
            return response

    return random.choice(_FALLBACKS)
