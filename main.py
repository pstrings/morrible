import os
import logging
import asyncio
import time

import discord
from discord.ext import commands
from dotenv import load_dotenv

from database.database import init_db
from keep_alive import keep_alive

# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("morrible")

# Bot class


class Morrible(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.load_extension("cogs.moderation")
        await self.load_extension("cogs.partnership")
        await self.tree.sync()
        logger.info("Cogs loaded and slash commands synced.")


async def start_bot():
    await init_db()
    logger.info("Database initialized.")
    bot = Morrible()
    async with bot:
        await bot.start(DISCORD_TOKEN)


def run_main():
    # Start Flask web server first to satisfy Render
    # keep_alive()

    time.sleep(5)
    # Start the bot
    asyncio.run(start_bot())


if __name__ == "__main__":
    run_main()
