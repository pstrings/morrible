import os
import logging
import asyncio

import discord
from discord.ext import commands
from dotenv import load_dotenv

from database.infraction import init_db
from keep_alive import keep_alive

load_dotenv()

keep_alive()


class Morrible(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.load_extension("cogs.moderation")
        # Registers slash commands
        await self.tree.sync()


if __name__ == "__main__":
    async def main():
        await init_db()
        bot = Morrible()
        await bot.run(os.getenv("DISCORD_TOKEN"), log_level=logging.DEBUG)

    asyncio.run(main())
