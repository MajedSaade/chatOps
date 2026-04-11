import logging
import asyncio
import os

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from app.commands import get_aws_cost, get_cluster_health, get_logs

logger = logging.getLogger("discord-bot")
GATEWAY_ERROR_MESSAGE = "I couldn't reach the AI gateway right now. Please try again shortly."


class GatewayBot:
    def __init__(self, token: str) -> None:
        intents = discord.Intents.default()
        intents.message_content = True

        self.token = token
        self.ai_gateway_url = os.getenv("AI_GATEWAY_URL", "").strip()
        self.ai_gateway_timeout_seconds = int(os.getenv("AI_GATEWAY_TIMEOUT_SECONDS", "30"))
        self.client = commands.Bot(command_prefix="!", intents=intents)
        self._presence_task: asyncio.Task | None = None
        self._synced = False
        self._register_events()
        self._register_slash_commands()

    @staticmethod
    def _extract_first_image_url(message: discord.Message) -> str | None:
        for attachment in message.attachments:
            content_type = (attachment.content_type or "").lower()
            filename = attachment.filename.lower()
            if content_type.startswith("image/") or filename.endswith(
                (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
            ):
                return attachment.url
        return None

    async def _build_gateway_payload(self, message: discord.Message) -> dict[str, str | None]:
        return {
            "user_id": str(message.author.id),
            "command_text": message.content,
            "image_url": self._extract_first_image_url(message),
        }

    async def _relay_to_gateway(self, payload: dict[str, str | None]) -> str:
        if not self.ai_gateway_url:
            raise RuntimeError("AI_GATEWAY_URL is not configured")

        timeout = aiohttp.ClientTimeout(total=self.ai_gateway_timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(self.ai_gateway_url, json=payload) as response:
                if response.status >= 400:
                    body = await response.text()
                    raise RuntimeError(
                        f"Gateway returned HTTP {response.status}: {body[:300]}"
                    )

                data = await response.json()
                for key in ("text", "response", "result", "message"):
                    value = data.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()

                raise RuntimeError("Gateway response JSON did not include a text field")

    async def _set_online_presence(self) -> None:
        await self.client.change_presence(
            status=discord.Status.online,
            activity=discord.Activity(
                type=discord.ActivityType.listening,
                name="your messages",
            ),
        )

    def _register_events(self) -> None:
        @self.client.event
        async def on_connect() -> None:
            logger.info("Gateway connected")

        @self.client.event
        async def on_ready() -> None:
            await self._set_online_presence()
            if not self._synced:
                await self.client.tree.sync()
                self._synced = True
                logger.info("Slash commands synced globally")

            logger.info("Bot online as %s (ID: %s)", self.client.user, self.client.user.id)
            logger.info("Listening in %d server(s)", len(self.client.guilds))

            # Refresh presence occasionally so reconnects/UI desyncs self-heal.
            if self._presence_task is None or self._presence_task.done():
                self._presence_task = self.client.loop.create_task(self._presence_refresher())

        @self.client.event
        async def on_resumed() -> None:
            await self._set_online_presence()
            logger.info("Session resumed; presence refreshed")

        @self.client.event
        async def on_message(message: discord.Message) -> None:
            if message.author.bot:
                return

            await self.client.process_commands(message)

            if message.content.strip().startswith("!"):
                return

            payload = await self._build_gateway_payload(message)
            logger.info("Relaying payload for user %s", payload["user_id"])

            try:
                async with message.channel.typing():
                    response_text = await self._relay_to_gateway(payload)
                await message.reply(response_text, mention_author=False)
            except (RuntimeError, aiohttp.ClientError, aiohttp.ContentTypeError, asyncio.TimeoutError):
                logger.exception("Gateway relay request failed")
                await message.reply(GATEWAY_ERROR_MESSAGE, mention_author=False)

    async def _presence_refresher(self) -> None:
        while not self.client.is_closed():
            try:
                await asyncio.sleep(300)
                await self._set_online_presence()
            except Exception:
                logger.exception("Periodic presence refresh failed")

    def _register_slash_commands(self) -> None:
        @self.client.tree.command(
            name="cluster-health",
            description="Show pod status summary for the configured K8s namespace",
        )
        async def cluster_health(interaction: discord.Interaction) -> None:
            await interaction.response.defer(thinking=True)
            await interaction.followup.send(get_cluster_health())

        @self.client.tree.command(
            name="logs",
            description="Fetch the last 50 log lines for a specific pod",
        )
        @app_commands.describe(pod_name="Name of the pod to fetch logs from")
        async def logs(interaction: discord.Interaction, pod_name: str) -> None:
            await interaction.response.defer(thinking=True)
            await interaction.followup.send(get_logs(pod_name))

        @self.client.tree.command(
            name="aws-cost",
            description="Show month-to-date AWS cost from Cost Explorer",
        )
        async def aws_cost(interaction: discord.Interaction) -> None:
            await interaction.response.defer(thinking=True)
            await interaction.followup.send(get_aws_cost())

    async def start(self) -> None:
        await self.client.start(self.token)