import logging
import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from app.chat import OllamaError, ask_ollama, get_response
from app.commands import get_aws_cost, get_cluster_health, get_logs

logger = logging.getLogger("discord-bot")
LLM_ERROR_MESSAGE = "I couldn't connect to my local brain. Make sure Ollama is running!"


class GatewayBot:
    def __init__(self, token: str) -> None:
        intents = discord.Intents.default()
        intents.message_content = True

        self.token = token
        self.client = commands.Bot(command_prefix="!", intents=intents)
        self._presence_task: asyncio.Task | None = None
        self._synced = False
        self._register_events()
        self._register_slash_commands()

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

            content = message.content.strip()
            if content.startswith("!"):
                return

            was_mentioned = False
            if self.client.user is not None:
                was_mentioned = self.client.user in message.mentions
                content = content.replace(f"<@{self.client.user.id}>", "").strip()
                content = content.replace(f"<@!{self.client.user.id}>", "").strip()

            if not content:
                content = "hi"

            logger.info("Message from %s: %s", message.author, content[:120])

            if was_mentioned:
                try:
                    async with message.channel.typing():
                        response = await ask_ollama(content)
                    await message.reply(response, mention_author=False)
                except OllamaError:
                    logger.exception("Mention-based Ollama request failed")
                    await message.reply(LLM_ERROR_MESSAGE, mention_author=False)
                return

            async with message.channel.typing():
                response = get_response(content)
            await message.reply(response, mention_author=False)

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

        @self.client.tree.command(
            name="ask",
            description="Ask the local Ollama model a question",
        )
        @app_commands.describe(prompt="Prompt to send to your local Ollama model")
        async def ask(interaction: discord.Interaction, prompt: str) -> None:
            await interaction.response.defer(thinking=True)
            try:
                response = await ask_ollama(prompt)
                await interaction.followup.send(response)
            except OllamaError:
                logger.exception("Slash /ask Ollama request failed")
                await interaction.followup.send(LLM_ERROR_MESSAGE)

    async def start(self) -> None:
        await self.client.start(self.token)