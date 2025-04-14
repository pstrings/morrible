import os
import logging

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()


class Morrible(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.load_extension("cogs.moderation")
        await self.tree.sync()  # Registers slash commands


if __name__ == "__main__":
    bot = Morrible()
    bot.run(os.getenv("DISCORD_TOKEN"), log_level=logging.DEBUG)
