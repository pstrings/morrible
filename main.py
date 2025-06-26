"""Main Bot file"""

import os
import logging
import asyncio

import discord
from discord.ext import commands
from dotenv import load_dotenv

from database.database import init_db

# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("morrible")


# Bot class

class Morrible(commands.AutoShardedBot):
    """Main class"""

    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)

    async def setup_hook(self):
        await self.load_extension("cogs.moderation")
        await self.load_extension("cogs.partnership")
        await self.load_extension("cogs.reaction_roles")
        logger.info("Cogs loaded")

    async def on_ready(self):
        print(f'Logged in as {self.user}')
        await self.sync_commands_with_backoff()
        logger.info("Cogs synced globally.")

    async def on_guild_join(self, guild: discord.Guild):
        """Sync slash commands when the bot joins a new guild."""

        try:
            synced = await self.tree.sync(guild=guild)
            logger.info("Synced %d slash commands for guild %s (%d) on join.", len(
                synced), guild.name, guild.id)
        except discord.HTTPException as e:
            logger.error(
                "Failed to sync guild commands for %s (%d) on join: %s", guild.name, guild.id, e)

    async def sync_commands_with_backoff(self, retries=5):
        """Syncs slash commands with retry and exponential backoff."""

        delay = 2
        for attempt in range(retries):
            try:
                await self.tree.sync()
                logger.info("Slash commands synced successfully.")
                return
            except discord.HTTPException as e:
                logger.warning(
                    "Slash sync failed (attempt %d): %s", attempt + 1, e)
                if attempt < retries - 1:
                    await asyncio.sleep(delay)
                    delay *= 2
                else:
                    logger.error(
                        "Failed to sync commands after several attempts.")


async def start_bot():
    """Start the bot"""
    await init_db()
    logger.info("Database initialized.")
    bot = Morrible()
    async with bot:
        await bot.start(DISCORD_TOKEN)


def run_main():
    """Run the bot"""

    asyncio.run(start_bot())


if __name__ == "__main__":
    run_main()
