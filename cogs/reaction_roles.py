import discord
from discord.ext import commands
from discord import app_commands

import json
from typing import Dict
from pathlib import Path

DATA_FILE = Path("database/reaction_roles.json")


def load_reaction_roles() -> Dict[int, Dict[str, int]]:
    if not DATA_FILE.exists():
        return {}
    try:
        with DATA_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
            return {int(k): {emoji: int(rid) for emoji, rid in v.items()} for k, v in data.items()}
    except (json.JSONDecodeError, ValueError):
        print("⚠️ Failed to load reaction roles JSON.")
        return {}


def save_reaction_roles(data: Dict[int, Dict[str, int]]):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with DATA_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


class ReactionRoles(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.reaction_role_messages: Dict[int,
                                          Dict[str, int]] = load_reaction_roles()

    @app_commands.command(name="setreactionroles", description="Set up emoji reactions to assign roles on a message.")
    @app_commands.describe(
        message_id="The message to attach reaction roles to",
        emoji1="First emoji (e.g. 😀)",
        role1="Role given when user reacts with emoji1",
        emoji2="Second emoji (optional)",
        role2="Role given when user reacts with emoji2 (optional)"
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_roles=True)
    async def setreactionroles(
        self,
        interaction: discord.Interaction,
        message_id: str,
        emoji1: str,
        role1: discord.Role,
        emoji2: str = None,
        role2: discord.Role = None
    ):
        await interaction.response.defer(ephemeral=True)

        try:
            msg_id = int(message_id)
        except ValueError:
            return await interaction.followup.send("❌ Invalid message ID.", ephemeral=True)

        try:
            message = await interaction.channel.fetch_message(msg_id)
        except discord.NotFound:
            return await interaction.followup.send("❌ Message not found in this channel.", ephemeral=True)
        except discord.Forbidden:
            return await interaction.followup.send("❌ Missing permission to fetch that message.", ephemeral=True)

        emoji_role_map = {}
        if emoji1 and role1:
            emoji_role_map[emoji1] = role1.id
        if emoji2 and role2:
            emoji_role_map[emoji2] = role2.id

        for emoji in emoji_role_map.keys():
            try:
                await message.add_reaction(emoji)
            except discord.HTTPException:
                await interaction.followup.send(f"⚠️ Could not react with {emoji} (invalid or permission issue).", ephemeral=True)

        self.reaction_role_messages[msg_id] = emoji_role_map
        save_reaction_roles(self.reaction_role_messages)

        await interaction.followup.send(
            f"✅ Reaction roles set up for message `{msg_id}`.",
            ephemeral=True
        )

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
