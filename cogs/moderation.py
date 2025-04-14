"""
This cog will run the moderation commands like warn, mute, timeout, kick, ban
"""
import discord
from discord.ext import commands
from discord import app_commands

ROLE_HIERARCHY = {
    "the good witch": 3,
    "the wicked witch": 3,
    "s": 3,
    "d": 3,
    "moderator": 2,
    "trainee staff": 1
}


def role_level(name: str) -> str:
    """Returns a role"""
    return ROLE_HIERARCHY.get(name.lower(), -1)


def require_role(min_level: int):
    """Check require role level"""
    async def predicate(interaction):
        user_roles = [role.name.lower() for role in interaction.author.roles]
        user_max = max((role_level(role) for role in user_roles), default=-1)
        if user_max >= min_level:
            return True
        raise commands.CheckFailure(
            "You don't have permission to use that command")
    return commands.check(predicate)


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="warn", description="Warn a member with a reason via DM")
    @app_commands.describe(member="The user to warn", reason="Why are they being warned?")
    @require_role(1)
    async def warn(self, interaction: discord.Interaction, member: discord.Member, *, reason: str):
        """Warns a member in the server"""

        # Prevent self-warn
        if member.id == interaction.user.id:
            return await interaction.response.send_message("You cannot warn yourself.", ephemeral=False)

        # Prevent warning the bot
        if member.id == self.bot.user.id:
            return await interaction.response.send_message("You cannot warn the bot.", ephemeral=False)

        # Role heirarchy check
        def get_role_level(user: discord.Member):
            return max((role_level(role.name.lower()) for role in user.roles), default=-1)

        issuer_level = get_role_level(interaction.user)
        target_level = get_role_level(member)

        if issuer_level <= target_level:
            return await interaction.response.send_message("You cannot warn someone with an equal or higher role.", ephemeral=False)

        try:
            await member.send(f"{member.mention} has been warned for: {reason or 'No reason provided.'}")
            await interaction.response.send_message(f"{member.mention} has been warned via DM.", ephemeral=False)
        except discord.Forbidden:
            await interaction.response.send_message(f"{member.mention} could not be warned via DM (they have DMs disabled)", ephemeral=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
