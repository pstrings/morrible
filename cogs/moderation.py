"""
This cog will run the moderation commands like warn, mute, timeout, kick, ban
"""
import discord
from discord.ext import commands

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
    async def predicate(ctx):
        user_roles = [role.name.lower() for role in ctx.author.roles]
        user_max = max((role_level(role) for role in user_roles), default=-1)
        if user_max >= min_level:
            return True
        raise commands.CheckFailure(
            "You don't have permission to use that command")
    return commands.check(predicate)


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="warn")
    @require_role(1)
    async def warn(self, ctx, member: discord.Member, *, reason=None):
        """Warns a member in the server"""
        try:
            await member.send(f"{member.mention} has been warned for: {reason or 'No reason provided.'}")
            await ctx.send(f"{member.mention} has been warned via DM.")
        except discord.Forbidden:
            await ctx.send(f"{member.mention} could not be warned via DM (they have DMs disabled)")


async def setup(bot):
    await bot.add_cog(Moderation(bot))
