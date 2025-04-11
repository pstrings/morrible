import os
import logging

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"We have logged in as {bot.user}")
    await bot.load_extension("cogs.moderation")

if __name__ == "__main__":
    bot.run(os.getenv("DISCORD_TOKEN"), log_level=logging.DEBUG)
