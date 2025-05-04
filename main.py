import os
import logging
import asyncio

import discord
from discord.ext import commands
from dotenv import load_dotenv

from database.database import init_db
from keep_alive import keep_alive

# Load environment variables
load_dotenv()

# Start Flask Web Server
keep_alive()

# Configure Logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("morrible")


class Morrible(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.load_extension("cogs.moderation")
        await self.load_extension("cogs.partnership")
        # Registers slash commands
        await self.tree.sync()
        logger.info("Cogs loaded and slash commands synced.")


async def main():
    """Main function"""

    logger.info("Initializing database...")
    await init_db()
    logger.info("Database initialized.")

    bot = Morrible()
    logger.info("Starting bot...")
    async with bot:
        await bot.start(os.getenv("DISCORD_TOKEN"))

if __name__ == "__main__":
    asyncio.run(main())
