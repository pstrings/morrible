"""
This cog will run the moderation commands like warn, mute, timeout, kick, ban
"""
import datetime
from collections import Counter
from typing import Callable, Tuple

import discord
from discord.ext import commands
from discord import app_commands, Embed
from discord.ui import View, Button
from sqlalchemy import select

from database.database import async_session, Infraction, ModLogChannel

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


def parse_duration(duration_str: str) -> datetime.timedelta | None:
    """Parses a duration string (e.g., 1h30m) into a timedelta object."""

    import re
    pattern = re.compile(r"(\d+)([smhd])")
    matches = pattern.findall(duration_str.lower())

    if not matches:
        return None

    total_seconds = 0
    for amount, unit in matches:
        amount = int(amount)
        if unit == "s":
            total_seconds += amount

        elif unit == "m":
            total_seconds += amount * 60

        elif unit == "h":
            total_seconds += amount * 3600

        elif unit == "d":
            total_seconds += amount * 86400

    return datetime.timedelta(seconds=total_seconds)


def get_highest_role_level(user: discord.Member) -> int:
    """Get Highest Role Level"""

    return max((role_level(role.name.lower()) for role in user.roles), default=-1)


async def get_or_create_muted_role(guild: discord.Guild):
    """Get or Create Muted Role"""

    muted_role = discord.utils.get(guild.roles, name="Muted")

    if muted_role is None:
        try:
            muted_role = await guild.create_role(name="Muted", reason="To silence the disobedient")

            # Set permission in all channels
            for channel in guild.channels:
                await channel.set_permissions(muted_role, send_messages=False, speak=False, add_reaction=False)

        except discord.Forbidden:
            return None
        except Exception as e:
            print(f"Failed to create Muted role: {e}")
            return None

    return muted_role


async def save_infraction(user_id: int, moderator_id: int, infraction_type: str, reason: str, duration_seconds: int = None):
    """Save user infractions in database"""

    async with async_session() as session:
        new_infraction = Infraction(
            user_id=user_id,
            moderator_id=moderator_id,
            infraction_type=infraction_type,
            reason=reason,
            duration_seconds=duration_seconds
        )

        session.add(new_infraction)
        await session.commit()


async def send_mod_log(
    bot,
    guild: discord.Guild,
    action: str,
    moderator: discord.User,
    target: discord.User = None,
    reason: str = None,
    duration: str = None,
    extra: str = None
):
    async with async_session() as session:
        log_channel_entry = await session.get(ModLogChannel, guild.id)
        if not log_channel_entry:
            return  # No mod log channel set

        log_channel = guild.get_channel(log_channel_entry.channel_id)
        if not log_channel:
            return  # Channel no longer exists

        embed = discord.Embed(
            title=f"🛠️ Moderation Action: {action}",
            color=discord.Color.orange()
        )

        if target:
            embed.set_thumbnail(url=target.display_avatar.url)
            embed.add_field(
                name="Target", value=f"{target} (`{target.id}`)", inline=False)

        embed.add_field(name="Moderator",
                        value=f"{moderator} (`{moderator.id}`)", inline=False)

        if duration:
            embed.add_field(name="Duration", value=duration, inline=False)

        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)

        if extra:
            embed.add_field(name="Details", value=extra, inline=False)

        embed.set_footer(text=f"Action taken in {guild.name}")
        embed.timestamp = discord.utils.utcnow()

        await log_channel.send(embed=embed)


class PaginatedEmbedView(View):
    """Generalized Paginated View"""

    def __init__(
        self,
        entries: list,
        per_page: int = 5,
        title: str = "Entries",
        formatter: Callable = None,
        color: discord.Color = discord.Color.blurple()
    ):
        super().__init__(timeout=60)
        self.entries = entries
        self.per_page = per_page
        self.current_page = 0
        self.max_pages = (len(entries) - 1) // per_page + 1
        self.title = title
        self.formatter = formatter or (lambda x: (str(x), ""))
        self.color = color

        self.prev_button = Button(
            label="Previous", style=discord.ButtonStyle.primary)
        self.next_button = Button(
            label="Next", style=discord.ButtonStyle.primary)

        self.prev_button.callback = self.prev_page
        self.next_button.callback = self.next_page

        self.update_buttons()
        self.add_item(self.prev_button)
        self.add_item(self.next_button)

    def update_buttons(self):
        self.prev_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page >= self.max_pages - 1

    def get_embed(self):
        start = self.current_page * self.per_page
        end = start + self.per_page
        entries = self.entries[start:end]

        embed = discord.Embed(title=self.title, color=self.color)
        for entry in entries:
            name, value = self.formatter(entry)
            embed.add_field(name=name, value=value, inline=False)

        embed.set_footer(text=f"Page {self.current_page + 1}/{self.max_pages}")
        return embed

    async def prev_page(self, interaction: discord.Interaction):
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def next_page(self, interaction: discord.Interaction):
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # Warn a member

    @app_commands.command(name="warn", description="Warn a member with a reason via DM")
    @app_commands.describe(member="The user to warn", reason="Why are they being warned?")
    @app_commands.guild_only()
    @app_commands.guild_install()
    @require_role(1)
    async def warn(self, interaction: discord.Interaction, member: discord.Member, *, reason: str):
        """Warns a member in the server"""

        # Prevent self-warn
        if member.id == interaction.user.id:
            return await interaction.response.send_message("You cannot warn yourself.", ephemeral=False)

        # Prevent warning the bot
        if member.id == self.bot.user.id:
            return await interaction.response.send_message("You cannot warn the bot.", ephemeral=False)

        issuer_level = get_highest_role_level(interaction.user)
        target_level = get_highest_role_level(member)

        if issuer_level <= target_level:
            return await interaction.response.send_message("You cannot warn someone with an equal or higher role.", ephemeral=False)

        try:
            await member.send(f"{member.mention} has been warned for: {reason}")
            await interaction.response.send_message(f"{member.mention} has been warned via DM.", ephemeral=False)

            await save_infraction(
                user_id=member.id,
                moderator_id=interaction.user.id,
                infraction_type="warn",
                reason=reason
            )

            await send_mod_log(self.bot, interaction.guild, "Warn", interaction.user, member, reason)

        except discord.Forbidden:
            await interaction.response.send_message(f"{member.mention} could not be warned via DM (they have DMs disabled)", ephemeral=False)

    # Kick a member

    @app_commands.command(name="kick", description="Kick a member with a reason via DM")
    @app_commands.describe(member="The user to kick", reason="Why are they being kicked?")
    @app_commands.guild_only()
    @app_commands.guild_install()
    @require_role(2)
    async def kick(self, interaction: discord.Interaction, member: discord.Member, *, reason: str):
        """Kicks a member from the server"""
        # Prevent self kick
        if member.id == interaction.user.id:
            return await interaction.response.send_message("You are not allowed to kick yourself.", ephemeral=False)

        # Prevent kicking the bot
        if member.id == self.bot.user.id:
            return await interaction.response.send_message("You are not allowed to kick the bot", ephemeral=False)

        issuer_level = get_highest_role_level(interaction.user)
        target_level = get_highest_role_level(member)

        if issuer_level <= target_level:
            return await interaction.response.send_message("You cannot kick someone with an equal or higher role.", ephemeral=False)

        try:
            await member.send(f"{member.mention} has been kicked for: {reason}")
            await member.kick(reason=f"Kicked by {interaction.user} for: {reason}")
            await interaction.response.send_message(f"{member.mention} has been kicked from the server. Reason: {reason}", ephemeral=False)
            await save_infraction(
                user_id=member.id,
                moderator_id=interaction.user.id,
                infraction_type="kick",
                reason=reason
            )

            await send_mod_log(self.bot, interaction.guild, "Kick", interaction.user, member, reason)

        except discord.Forbidden:
            await interaction.response.send_message("I do not have permission to kick this user.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"An error occurred: {str(e)}", ephemeral=True)

    # Ban a member

    @app_commands.command(name="ban", description="Ban a member with a reason via DM")
    @app_commands.describe(member="The user to ban", reason="Why are they being banned?", delete_message_days="How many days of their messages to delete (0–7, optional)")
    @app_commands.guild_only()
    @app_commands.guild_install()
    @require_role(2)
    async def ban(self, interaction: discord.Interaction, member: discord.Member, *, reason: str, delete_message_days: int = 0):
        """Command to ban members from the server."""

        # Prevent self ban
        if member.id == interaction.user.id:
            await interaction.response.send_message("You are not allowed to ban yourself.", ephemeral=False)

        # Prevent banning the bot
        if member.id == self.bot.user.id:
            await interaction.response.send_message("You are not allowed to ban the bot", ephemeral=False)

        issuer_level = get_highest_role_level(interaction.user)
        target_level = get_highest_role_level(member)

        if issuer_level <= target_level:
            return await interaction.response.send_message("You cannot ban someone with an equal or higher role.", ephemeral=False)

        if delete_message_days < 0 or delete_message_days > 7:
            return await interaction.response.send_message("you can only delete messages upto 7 days. This number can not be less than 0.")

        await interaction.response.defer(thinking=False)

        try:
            try:
                await member.send(f"You have been banned from {interaction.guild.name} for: {reason}")
            except discord.Forbidden:
                await interaction.followup.send("I do not have permission to dm this user.", ephemeral=True)
            await member.ban(delete_message_days=delete_message_days, reason=reason)
            await interaction.followup.send(f"{member.mention} has been banned. Deleted last {delete_message_days} days of messages.", ephemeral=False)
            await save_infraction(
                user_id=member.id,
                moderator_id=interaction.user.id,
                infraction_type="ban",
                reason=reason
            )
            await send_mod_log(self.bot, interaction.guild, "Ban", interaction.user, member, reason)
        except discord.Forbidden:
            await interaction.followup.send("I do not have permission to ban this user.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"⚠️ An error occurred: `{str(e)}`", ephemeral=True)

    # Unban a member

    @app_commands.command(name="unban", description="Unban a member with a reason via DM")
    @app_commands.describe(user="The user to unban", reason="Reason for the unban")
    @app_commands.guild_only()
    @app_commands.guild_install()
    @require_role(3)
    async def unban(self, interaction: discord.Interaction, user: discord.User, *, reason: str):
        """This method will unban a user."""
        # Prevent self unban
        if user.id == interaction.user.id:
            await interaction.response.send_message("You are not allowed to unban yourself.", ephemeral=False)

        # Preventing unban on bot
        if user.id == self.bot.user.id:
            await interaction.response.send_message("You are not allowed to unban the bot.", ephemeral=False)

        # Check if user is banned
        banned_users = {}
        async for ban_entry in interaction.guild.bans():
            banned_users[ban_entry.user.id] = ban_entry

        if user.id not in banned_users:
            return await interaction.response.send_message(f"{user} is not currently banned.", ephemeral=False)

        try:
            await interaction.guild.unban(user, reason=f"Unbanned by {interaction.user} for: {reason}")

            await interaction.response.send_message(f"{user.mention} has been unbanned. Reason: {reason}", ephemeral=False)

            await send_mod_log(self.bot, interaction.guild, "Unban", interaction.user, user, reason)

        except discord.Forbidden:
            return await interaction.response.send_message("I don't have permission to unban that user.", ephemeral=False)

    # List all banned users

    @app_commands.command(name="listban", description="List all the banned users")
    @app_commands.guild_only()
    @app_commands.guild_install()
    @require_role(1)
    async def list_ban(self, interaction: discord.Interaction):
        await interaction.response.defer()

        bans = [entry async for entry in interaction.guild.bans()]
        if not bans:
            return await interaction.followup.send("There are no banned users.", ephemeral=False)

        def formatter(entry: discord.guild.BanEntry):
            user = entry.user
            reason = entry.reason
            name = f"{user.name}#{user.discriminator} (ID: {user.id})"
            value = f"Reason: {reason}"
            return name, value

        view = PaginatedEmbedView(
            entries=bans,
            per_page=10,
            title="🚫 Banned Users",
            formatter=formatter,
            color=discord.Color.purple()
        )
        await interaction.followup.send(embed=view.get_embed(), view=view)

    # Timeout Users

    @app_commands.command(name="timeout", description="Timeout members for a specific duration")
    @app_commands.describe(member="The member to timeout", duration="The timeout duration (Ex. 1h, 30m, 5m)", reason="Reason for the timeout")
    @app_commands.guild_only()
    @app_commands.guild_install()
    @require_role(1)
    async def timeout(self, interaction: discord.Interaction, member: discord.Member, duration: str, *, reason: str):
        """Timeout a member in the server."""

        if member.id == interaction.user.id:
            return await interaction.response.send_message("You cannot timeout yourself.", ephemeral=False)
        if member.id == self.bot.user.id:
            return await interaction.response.send_message("I cannot timeout myself.")

        issuer_level = get_highest_role_level(interaction.user)
        target_level = get_highest_role_level(member)

        if issuer_level <= target_level:
            return await interaction.response.send_message("You cannot timeout someone with an equal or higher role.")

        delta = parse_duration(duration)
        if delta is None:
            return await interaction.response.send_message("Invalid duration format. Please use formats like '1h', '30m', '5m', '1d12h'.")

        until = discord.utils.utcnow() + delta

        await interaction.response.defer()
        try:
            await member.timeout(until, reason=reason)
            await interaction.followup.send(f"{member.mention} has been timed out for {duration}. Reason: {reason}")
            try:
                await member.send(f"You have been timed out in {interaction.guild.name} for {duration}. Reason: {reason}")
                await save_infraction(
                    user_id=member.id,
                    moderator_id=interaction.user.id,
                    infraction_type="timeout",
                    reason=reason,
                    duration_seconds=until
                )
                await send_mod_log(self.bot, interaction.guild, "Timeout", interaction.user, member, reason, duration=duration)

            except discord.Forbidden:
                await interaction.followup.send("Could not DM the user about the timeout.")
        except discord.Forbidden:
            await interaction.followup.send("I do not have permission to timeout this user.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"An error occurred: {e}", ephemeral=True)

    # Remove Timeout

    @app_commands.command(name="untimeout", description="Remove the timeout from a member")
    @app_commands.describe(member="The member to remove the timeout from", reason="Reason for removing the timeout")
    @app_commands.guild_only()
    @app_commands.guild_install()
    @require_role(1)
    async def untimeout(self, interaction: discord.Interaction, member: discord.Member, *, reason: str):
        """Removes the timeout from a member."""
        if member.id == interaction.user.id:
            return await interaction.response.send_message("You cannot remove your own timeout.")
        if member.id == self.bot.user.id:
            return await interaction.response.send_message("I cannot remove my own timeout (I'm not timed out!).")

        issuer_level = get_highest_role_level(interaction.user)
        target_level = get_highest_role_level(member)

        if issuer_level <= target_level:
            return await interaction.response.send_message("You cannot remove the timeout from someone with an equal or higher role.")

        await interaction.response.defer()
        try:
            if member.timed_out_until is None:
                return await interaction.followup.send(f"{member.mention} is not currently timed out.")
            await member.timeout(None, reason=reason)
            await interaction.followup.send(f"Removed timeout from {member.mention}. Reason: {reason}")

            # Moderation log
            await send_mod_log(self.bot, interaction.guild, "Untimeout", interaction.user, member, reason)
            try:
                await member.send(f"Your timeout in {interaction.guild.name} has been removed. Reason: {reason}")
            except discord.Forbidden:
                await interaction.followup.send("Could not DM the user about the timeout removal.")
        except discord.Forbidden:
            await interaction.followup.send("I do not have permission to remove the timeout from this user.")
        except Exception as e:
            await interaction.followup.send(f"An error occurred: {e}")

    # Clear Messages

    @app_commands.command(name="purge", description="Delete a specific number of recent messages")
    @app_commands.describe(amount="The number of messages to delete (1-100)")
    @app_commands.guild_only()
    @app_commands.guild_install()
    @require_role(3)
    async def purge(self, interaction: discord.Interaction, amount: int):
        """Deletes a specified number of recent messages from the channel."""
        if amount < 0 or amount > 100:
            return await interaction.response.send_message("Amount must be between 1 and 100.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        try:
            # +1 to account for the command message itself
            deleted = await interaction.channel.purge(limit=amount + 1)
            await interaction.followup.send(f"Deleted {len(deleted) - 1} messages.")
            await send_mod_log(self.bot, interaction.guild, action="Purge", moderator=interaction.user, extra=f"Deleted {len(deleted) - 1} messages in {interaction.channel.mention}")

        except discord.Forbidden:
            await interaction.followup.send("I do not have permission to delete messages in this channel.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"An error occurred: {e}", ephemeral=True)

    # Slowmode

    @app_commands.command(name="slowmode", description="Set slowmode in a channel")
    @app_commands.describe(duration="Time (e.g. 5s, 2m, 1h)", channel="The channel to set slowmode in")
    @app_commands.guild_only()
    @app_commands.guild_install()
    @require_role(3)
    async def slowmode(self, interaction: discord.Interaction, duration: str, channel: discord.TextChannel = None):
        """Sets slowmode for a channel. If channel is not given, current channel is used."""
        delta = parse_duration(duration)
        if delta is None:
            return await interaction.response.send_message("❌ Invalid duration format. Use formats like `10s`, `5m`, `1h30m`")

        delay_seconds = int(delta.total_seconds())
        if delay_seconds < 0 or delay_seconds > 21600:
            return await interaction.response.send_message("❌ Slowmode must be between 0s and 6h (21600 seconds).")

        target_channel = channel or interaction.channel

        try:
            await target_channel.edit(slowmode_delay=delay_seconds)
            await interaction.response.send_message(f"✅ Slowmode set to `{duration}` seconds in {target_channel.mention}.")

            # Moderation Logs
            await send_mod_log(
                self.bot,
                interaction.guild,
                action="Slowmode Set",
                moderator=interaction.user,
                extra=f"Set to `{duration}` in {target_channel.mention}"
            )
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to edit this channel.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ An error occurred: {str(e)}", ephemeral=True)

    # Mute

    @app_commands.command(name="mute", description="Bestow silence upon a misbehaving soul.")
    @app_commands.describe(member="The miscreant to be muted", reason="Reason for the mute")
    @app_commands.guild_only()
    @app_commands.guild_install()
    @require_role(1)
    async def mute(self, interaction: discord.Interaction, member: discord.Member, *, reason: str):
        muted_role = await get_or_create_muted_role(interaction.guild)

        # Prevent self-mute
        if member.id == interaction.user.id:
            return await interaction.response.send_message("You cannot mute yourself.", ephemeral=False)

        # Prevent muting the bot
        if member.id == self.bot.user.id:
            return await interaction.response.send_message("You cannot mute the bot.", ephemeral=False)

        issuer_level = get_highest_role_level(interaction.user)
        target_level = get_highest_role_level(member)

        if issuer_level <= target_level:
            return await interaction.response.send_message("You cannot mute someone with an equal or higher role.", ephemeral=False)

        if not muted_role:
            return await interaction.response.send_message("I sought to summon the powers of silence, but was denied. An administrator must intervene.")

        if muted_role in member.roles:
            return await interaction.response.send_message(f"{member.mention} is already shackled by silence.")

        try:
            await member.add_roles(muted_role)
            await member.send(f"{member.mention} has been muted for: {reason}")
            await interaction.response.send_message(f"{member.mention} has been enveloped in a most unbreakable silence. A fitting end for their folly! Reason: {reason}")
            await save_infraction(
                user_id=member.id,
                moderator_id=interaction.user.id,
                infraction_type="mute",
                reason=reason
            )

            # Moderation log
            await send_mod_log(self.bot, interaction.guild, "Mute", interaction.user, member, reason)
        except discord.Forbidden:
            await interaction.response.send_message("Alas! I lack the authority to mute this illustrious being.")
        except Exception as e:
            await interaction.response.send_message(f"An error most foul has occurred: `{str(e)}`")

    # Auto add mute permissions on new channel creation

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        muted_role = discord.utils.get(channel.guild.roles, name="Muted")

        if muted_role:
            try:
                await channel.set_permissions(muted_role, send_messages=False, speak=False, add_reactions=False)
                print(
                    f"Updated Muted role permissions for new channel: {channel.name}")
            except Exception as e:
                print(
                    f"Failed to set permissions for new channel {channel.name}: {e}")

    # Unmute

    @app_commands.command(name="unmute", description="Restore the voice of a once-muted soul.")
    @app_commands.describe(member="The once-muted to be liberated")
    @app_commands.guild_only()
    @app_commands.guild_install()
    @require_role(1)
    async def unmute(self, interaction: discord.Interaction, member: discord.Member):
        muted_role = await get_or_create_muted_role(interaction.guild)

        if not muted_role:
            return await interaction.response.send_message("The forces of silence have left no trace. There is no muting to undo.", ephemeral=True)
            return

        if muted_role not in member.roles:
            return await interaction.response.send_message(f"{member.mention} is not among the silent ranks.", ephemeral=True)
            return

        try:
            await member.remove_roles(muted_role)
            await member.send(f"{member.mention} has been unmuted")
            await interaction.response.send_message(f"{member.mention} has been freed from their cursed silence. May they tread carefully henceforth.")
            # Moderation log
            await send_mod_log(self.bot, interaction.guild, "Unmute", interaction.user, member)
        except discord.Forbidden:
            await interaction.response.send_message("I cannot lift the silence from this soul. They are beyond my reach.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"A calamity most unexpected has occurred: `{str(e)}`", ephemeral=True)

    # List User Infractions:
    @app_commands.command(name="infractions", description="Show all infractions for a user by ID.")
    @app_commands.describe(user_id="The user ID to check infractions for.")
    @app_commands.guild_install()
    @require_role(1)
    async def infractions(self, interaction: discord.Interaction, user_id: str):
        """Shows all infractions for any user ID (even if not in server)"""
        try:
            user_id = int(user_id)
        except ValueError:
            return await interaction.response.send_message("❌ Invalid user ID.", ephemeral=False)

        async with async_session() as session:
            result = await session.execute(select(Infraction).where(Infraction.user_id == user_id))
            infractions = result.scalars().all()

        if not infractions:
            return await interaction.response.send_message("✅ This user has no infractions.")

        # Count summary
        counts = Counter(i.infraction_type.lower() for i in infractions)
        total = len(infractions)
        summary = f"Total: {total} | " + \
            " | ".join(f"{k.capitalize()}: {v}" for k, v in counts.items())

        def formatter(entry: Infraction) -> Tuple[str, str]:
            timestamp = entry.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            duration = f" | Duration: {entry.duration_seconds}s" if entry.duration_seconds else ""
            name = f"Type: {entry.infraction_type.upper()}"
            value = (
                f"Reason: {entry.reason or 'No reason provided'}\n"
                f"Date: {timestamp}{duration}\n"
                f"Moderator ID: {entry.moderator_id}"
            )
            return name, value

        view = PaginatedEmbedView(
            entries=infractions,
            per_page=5,
            title=f"Infractions for User ID: {user_id}",
            formatter=formatter,
            color=discord.Color.purple()
        )

        await interaction.response.send_message(content=summary, embed=view.get_embed(), view=view)

    # Clear Infractions for user
    @app_commands.command(name="clearinfractions", description="Clear all infractions for a user.")
    @app_commands.describe(user="The user to clear infractions for.")
    @app_commands.guild_only()
    @app_commands.guild_install()
    @require_role(3)
    async def clearinfractions(self, interaction: discord.Interaction, user: discord.Member):
        """To clear all infractions by a user."""
        async with async_session() as session:
            query = select(Infraction).where(Infraction.user_id == user.id)
            result = await session.execute(query)
            infractions = result.scalars().all()

            if not infractions:
                await interaction.response.send_message(f"✅ {user.mention} has no infractions to clear.", ephemeral=False)
                return

            for infraction in infractions:
                await session.delete(infraction)

            await session.commit()

            await interaction.response.send_message(f"🗑️ Cleared all infractions for {user.mention}.", ephemeral=False)

            # Moderation log
            await send_mod_log(self.bot, interaction.guild, "Clear Infraction", interaction.user, user)

    # Set mod log channel

    @app_commands.command(name="setmodlog", description="Set the moderation logs channel.")
    @app_commands.describe(channel="Channel for moderation logs")
    @app_commands.guild_only()
    @app_commands.guild_install()
    @require_role(3)
    async def set_mod_log(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Set channel for moderation logs"""

        guild_id = interaction.guild.id

        async with async_session as session:
            existing = await session.get(ModLogChannel, guild_id)
            if existing:
                existing.channel_id = channel.id
            else:
                session.add(ModLogChannel(guild_id, channel_id=channel.id))
            await session.commit()

        await interaction.response.send_message(f"✅ Mod log channel set to {channel.mention}")


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
