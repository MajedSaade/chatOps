import logging
import asyncio
import os
from uuid import uuid4

import discord
from discord import app_commands
from discord.ext import commands

from app.commands import (
    analyze_ollama,
    ask_ollama,
    detect_yolo,
    get_aws_cost,
    get_cluster_health,
    get_logs,
    run_gateway_command,
)

logger = logging.getLogger("discord-bot")


class GatewayBot:
    def __init__(self, token: str) -> None:
        intents = discord.Intents.default()
        intents.message_content = True

        self.token = token
        self.dev_guild_id = int(os.getenv("DISCORD_GUILD_ID", "0"))
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
                if self.dev_guild_id:
                    guild = discord.Object(id=self.dev_guild_id)
                    self.client.tree.clear_commands(guild=guild)
                    self.client.tree.copy_global_to(guild=guild)
                    guild_commands = await self.client.tree.sync(guild=guild)
                    logger.info(
                        "Slash commands synced to guild %s: %s",
                        self.dev_guild_id,
                        [command.name for command in guild_commands],
                    )
                else:
                    # Mirror global commands to each connected guild for faster availability.
                    for guild in self.client.guilds:
                        self.client.tree.clear_commands(guild=guild)
                        self.client.tree.copy_global_to(guild=guild)
                        guild_commands = await self.client.tree.sync(guild=guild)
                        logger.info(
                            "Slash commands synced to guild %s (%s): %s",
                            guild.id,
                            guild.name,
                            [command.name for command in guild_commands],
                        )

                # Avoid duplicate command entries by clearing global registrations
                # when we are serving guild-scoped commands.
                self.client.tree.clear_commands(guild=None)
                global_commands = await self.client.tree.sync()
                self._synced = True
                logger.info(
                    "Slash commands synced globally: %s",
                    [command.name for command in global_commands],
                )

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

            user_id = str(message.author.id)
            command_text = message.content
            image_url = self._extract_first_image_url(message)
            request_id = str(uuid4())

            logger.info(
                "discord.command.received request_id=%s source=message discord_user_id=%s discord_channel_id=%s has_image=%s",
                request_id,
                user_id,
                str(message.channel.id),
                bool(image_url),
            )

            async with message.channel.typing():
                response_text = await run_gateway_command(
                    user_id=user_id,
                    command_text=command_text,
                    image_url=image_url,
                    discord_channel_id=str(message.channel.id),
                    request_id=request_id,
                    source="discord-message",
                )
            await message.reply(response_text, mention_author=False)

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
            description="Send a prompt through the AI gateway",
        )
        @app_commands.describe(prompt="Prompt text to send to /ask")
        async def ask(interaction: discord.Interaction, prompt: str) -> None:
            await interaction.response.defer(thinking=True)
            request_id = str(uuid4())
            await interaction.followup.send(
                await ask_ollama(
                    str(interaction.user.id),
                    prompt,
                    request_id=request_id,
                    discord_channel_id=str(interaction.channel_id or ""),
                )
            )

        @self.client.tree.command(
            name="analyze",
            description="Run deep analysis on input text through the AI gateway",
        )
        @app_commands.describe(user_input="Text/data to analyze")
        async def analyze(interaction: discord.Interaction, user_input: str) -> None:
            await interaction.response.defer(thinking=True)
            request_id = str(uuid4())
            await interaction.followup.send(
                await analyze_ollama(
                    str(interaction.user.id),
                    user_input,
                    request_id=request_id,
                    discord_channel_id=str(interaction.channel_id or ""),
                )
            )

        @self.client.tree.command(
            name="detect",
            description="Run object detection through the AI gateway",
        )
        @app_commands.describe(image="Image file to run detection on")
        async def detect(interaction: discord.Interaction, image: discord.Attachment) -> None:
            await interaction.response.defer(thinking=True)
            request_id = str(uuid4())

            content_type = (image.content_type or "").lower()
            filename = image.filename.lower()
            if not content_type.startswith("image/") and not filename.endswith(
                (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
            ):
                await interaction.followup.send("⚠️ Please upload an image file for /detect.")
                return

            await interaction.followup.send(
                await detect_yolo(
                    str(interaction.user.id),
                    image.url,
                    request_id=request_id,
                    discord_channel_id=str(interaction.channel_id or ""),
                )
            )

    async def start(self) -> None:
        await self.client.start(self.token)