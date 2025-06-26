import discord
from discord.ext import commands
from discord import app_commands

import json
import os

from typing import Dict
from pathlib import Path

DATA_FILE = Path("database/reaction_roles.json")


def load_reaction_roles() -> Dict[int, Dict[str, int]]:
    """Load mappings from JSON file."""
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return {int(k): {emoji: int(rid) for emoji, rid in v.items()} for k, v in data.items()}
    except (json.JSONDecodeError, ValueError):
        print("⚠️ Failed to load reaction roles JSON.")
        return {}


def save_reaction_roles(data: Dict[int, Dict[str, int]]):
    """Save mappings to JSON file."""
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


class ReactionRoles(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.reaction_role_messages: Dict[int,
                                          Dict[str, int]] = load_reaction_roles()

    @app_commands.command(name="setreactionroles", description="Link reactions on a message to role assignments.")
    @app_commands.describe(
        message_id="The ID of the message you want to add reactions to",
        mapping="Comma-separated emoji:role_id pairs (e.g. 😀:1234,🔥:5678)"
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_roles=True)
    async def setreactionroles(
        self,
        interaction: discord.Interaction,
        message_id: str,
        mapping: str
    ):
        await interaction.response.defer(ephemeral=True)

        try:
            message_id = int(message_id)
        except ValueError:
            return await interaction.followup.send("Invalid message ID.", ephemeral=True)

        emoji_role_map = {}
        for pair in mapping.split(","):
            if ":" not in pair:
                continue
            emoji, role_id = pair.strip().split(":")
            try:
                emoji = emoji.strip()
                role_id = int(role_id.strip())
                emoji_role_map[emoji] = role_id
            except ValueError:
                return await interaction.followup.send(f"Invalid role ID in pair: {pair}", ephemeral=True)

        try:
            message = await interaction.channel.fetch_message(message_id)
        except discord.NotFound:
            return await interaction.followup.send("Message not found in this channel.", ephemeral=True)
        except discord.Forbidden:
            return await interaction.followup.send("Missing permissions to fetch that message.", ephemeral=True)

        for emoji in emoji_role_map:
            try:
                await message.add_reaction(emoji)
            except discord.HTTPException:
                await interaction.followup.send(f"⚠️ Could not react with {emoji} (invalid or no permission).", ephemeral=True)

        self.reaction_role_messages[message_id] = emoji_role_map
        save_reaction_roles(self.reaction_role_messages)

        await interaction.followup.send(f"✅ Reaction roles saved and reactions added for message `{message_id}`.", ephemeral=True)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.message_id not in self.reaction_role_messages:
            return

        emoji = str(payload.emoji)
        role_id = self.reaction_role_messages[payload.message_id].get(emoji)
        if not role_id:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        member = guild.get_member(payload.user_id)
        if not member or member.bot:
            return

        role = guild.get_role(role_id)
        if role:
            try:
                await member.add_roles(role, reason="Reaction role added.")
            except discord.Forbidden:
                pass

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if payload.message_id not in self.reaction_role_messages:
            return

        emoji = str(payload.emoji)
        role_id = self.reaction_role_messages[payload.message_id].get(emoji)
        if not role_id:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        member = guild.get_member(payload.user_id)
        if not member or member.bot:
            return

        role = guild.get_role(role_id)
        if role:
            try:
                await member.remove_roles(role, reason="Reaction role removed.")
            except discord.Forbidden:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(ReactionRoles(bot))
    print("✅ Loaded ReactionRoles Cog")
