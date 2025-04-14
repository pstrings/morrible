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
    async def predicate(interaction: discord.Interaction):
        user_roles = [role.name.lower() for role in interaction.user.roles]
        user_max = max((role_level(role) for role in user_roles), default=-1)
        if user_max >= min_level:
            return True
        raise app_commands.CheckFailure(
            "You don't have permission to use that command")
    return app_commands.check(predicate)


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="warn", description="Warn a member with a reason via DM")
    @app_commands.describe(member="The user to warn", reason="Why are they being warned?")
    @app_commands.guild_only()
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

    @app_commands.command(name="kick", description="Kick a member with a reason via DM")
    @app_commands.describe(member="The user to kick", reason="Why are they being kicked?")
    @app_commands.guild_only()
    @require_role(2)
    async def kick(self, interaction: discord.Interaction, member: discord.Member, *, reason: str):
        """Kicks a member from the server"""
        # Prevent self kick
        if member.id == interaction.user.id:
            return await interaction.response.send_message("You are not allowed to kick yourself.", ephemeral=False)

        # Prevent kicking the bot
        if member.id == self.bot.user.id:
            return await interaction.response.send_message("You are not allowed to kick the bot", ephemeral=False)

        # Role heirarchy check
        def get_role_level(user: discord.Member):
            return max((role_level(role.name.lower()) for role in user.roles), default=-1)

        issuer_level = get_role_level(interaction.user)
        target_level = get_role_level(member)

        if issuer_level <= target_level:
            return await interaction.response.send_message("You cannot kick someone with an equal or higher role.", ephemeral=False)

        try:
            await member.send(f"{member.mention} has been kicked for: {reason or 'No reason provided.'}")
            await member.kick(reason=f"Kicked by {interaction.user} for: {reason}")
            await interaction.response.send_message(f"{member.mention} has been kicked from the server. Reason: {reason}", ephemeral=False)
        except discord.Forbidden:
            await interaction.response.send_message("I do not have permission to kick this user.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"An error occurred: {str(e)}", ephemeral=True)

    @app_commands.command(name="ban", description="Ban a member with a reason via DM")
    @app_commands.describe(member="The user to ban", reason="Why are they being banned?", delete_message_days="How many days of their messages to delete (0–7, optional)")
    @app_commands.guild_only()
    @require_role(2)
    async def ban(self, interaction: discord.Interaction, member: discord.Member, *, reason: str, delete_message_days: int = 0):
        """Command to ban members from the server."""
        # Prevent self ban
        if member.id == interaction.user.id:
            await interaction.response.send_message("You are not allowed to ban yourself.", ephemeral=False)

        # Prevent banning the bot
        if member.id == self.bot.user.id:
            await interaction.response.send_message("You are not allowed to ban the bot", ephemeral=False)

        # Role heirarchy check
        def get_role_level(user: discord.Member):
            return max((role_level(role.name.lower()) for role in user.roles), default=-1)

        issuer_level = get_role_level(interaction.user)
        target_level = get_role_level(member)

        if issuer_level <= target_level:
            return await interaction.response.send_message("You cannot ban someone with an equal or higher role.", ephemeral=False)

        if delete_message_days < 0 or delete_message_days > 7:
            return await interaction.response.send_message("you can only delete messages upto 7 days. This number can not be less than 0.")

        try:
            try:
                await member.send(f"You have been banned from {interaction.guild.name} for: {reason or 'No reason provided.'}")
            except discord.Forbidden:
                await interaction.response.send_message("I do not have permission to dm this user.", ephemeral=True)
            await member.ban(delete_message_days=delete_message_days, reason=reason)
            await interaction.response.send_message(f"{member.mention} has been banned. Deleted last {delete_message_days} days of messages.", ephemeral=False)
        except discord.Forbidden:
            await interaction.response.send_message("I do not have permission to ban this user.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"⚠️ An error occurred: `{str(e)}`", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
    print(
        f"Loaded moderation cog with commands: {[cmd.name for cmd in bot.tree.get_commands()]}")
