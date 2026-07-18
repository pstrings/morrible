"""
This cog will run the moderation commands like warn, mute, timeout, kick, ban
"""
import datetime
import logging
import io
from collections import Counter
from typing import Callable, Tuple

import discord
from discord.ext import commands
from discord import app_commands, Embed
from discord.ui import View, Button
from sqlalchemy import select

from database.database import async_session, Infraction, ModLogChannel, ExcludedChannel

logger = logging.getLogger("morrible")

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
            "My dear, you lack the necessary *stature* to command me in such a way.")
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
            color=discord.Color.purple()
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
            return await interaction.response.send_message("Oh, you mustn't be so hard on yourself. Leave the chastising to me.", ephemeral=False)

        # Prevent warning the bot
        if member.id == self.bot.user.id:
            return await interaction.response.send_message("You think you can warn *me*? How... droll.", ephemeral=False)

        issuer_level = get_highest_role_level(interaction.user)
        target_level = get_highest_role_level(member)

        if issuer_level <= target_level:
            return await interaction.response.send_message("One must know their place, darling. You cannot warn those of equal or greater importance.", ephemeral=False)

        try:
            await member.send(f"A little birdie has whispered a warning in your ear, {member.mention}, for: {reason}")
            await interaction.response.send_message(f"A little birdie has whispered a warning in {member.mention}'s ear. Let's hope they listen.", ephemeral=False)

            await save_infraction(
                user_id=member.id,
                moderator_id=interaction.user.id,
                infraction_type="warn",
                reason=reason
            )

            await send_mod_log(self.bot, interaction.guild, "Warn", interaction.user, member, reason)

        except discord.Forbidden:
            await interaction.response.send_message(f"It seems {member.mention} has shut themselves away from my... *guidance*. How unfortunate for them.", ephemeral=False)

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
            return await interaction.response.send_message("My dear, self-sabotage is so... unbecoming. You can't possibly kick yourself.", ephemeral=False)

        # Prevent kicking the bot
        if member.id == self.bot.user.id:
            return await interaction.response.send_message("You wish to kick *me*? Oh, that's rich. Utterly, utterly rich.", ephemeral=False)

        issuer_level = get_highest_role_level(interaction.user)
        target_level = get_highest_role_level(member)

        if issuer_level <= target_level:
            return await interaction.response.send_message("One must respect the hierarchy of talent, my dear. You cannot kick your equals or superiors.", ephemeral=False)

        try:
            await member.send(f"You have been... *escorted* from our presence, {member.mention}, for: {reason}")
            await member.kick(reason=f"Kicked by {interaction.user} for: {reason}")
            await interaction.response.send_message(f"{member.mention} has been... *escorted* from our presence. A necessary, if unpleasant, business.", ephemeral=False)
            await save_infraction(
                user_id=member.id,
                moderator_id=interaction.user.id,
                infraction_type="kick",
                reason=reason
            )

            await send_mod_log(self.bot, interaction.guild, "Kick", interaction.user, member, reason)

        except discord.Forbidden:
            await interaction.response.send_message("Alas, my influence does not extend to this... *particular* individual. A pity.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"A most unexpected and *dreadful* complication has arisen: {str(e)}", ephemeral=True)

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
            await interaction.response.send_message("Banish *yourself*? Oh, the melodrama! No, no, that simply won't do.", ephemeral=False)

        # Prevent banning the bot
        if member.id == self.bot.user.id:
            await interaction.response.send_message("You want to ban *me*? Oh, you do have a flair for the dramatic. But no.", ephemeral=False)

        issuer_level = get_highest_role_level(interaction.user)
        target_level = get_highest_role_level(member)

        if issuer_level <= target_level:
            return await interaction.response.send_message("There are some people, my dear, who are simply... untouchable. At least by you.", ephemeral=False)

        if delete_message_days < 0 or delete_message_days > 7:
            return await interaction.response.send_message("A week is more than enough time to erase any... *unpleasantness*. We mustn't be excessive.", ephemeral=False)

        await interaction.response.defer(thinking=False)

        # Initialize purged message IDs cache on bot if not present
        if not hasattr(self.bot, "purged_message_ids"):
            self.bot.purged_message_ids = set()

        if delete_message_days > 0:
            try:
                all_ban_messages = []
                cutoff = discord.utils.utcnow() - datetime.timedelta(days=delete_message_days)
                channels_to_search = []
                for ch in interaction.guild.text_channels:
                    perms = ch.permissions_for(interaction.guild.me)
                    if perms.read_messages:
                        channels_to_search.append(ch)

                # Filter out excluded channels using DB
                async with async_session() as session:
                    result = await session.execute(
                        select(ExcludedChannel).where(ExcludedChannel.guild_id == interaction.guild.id)
                    )
                    excluded_ids = {entry.channel_id for entry in result.scalars().all()}

                channels_to_search = [ch for ch in channels_to_search if ch.id not in excluded_ids]

                for ch in channels_to_search:
                    try:
                        async for msg in ch.history(after=cutoff, limit=None):
                            if msg.author.id == member.id:
                                all_ban_messages.append(msg)
                                self.bot.purged_message_ids.add(msg.id)
                    except Exception as e:
                        logger.error("Failed to fetch history for channel %s during ban: %s", ch.name, e)

                # Generate target purge log report
                if all_ban_messages:
                    all_ban_messages = sorted(all_ban_messages, key=lambda m: m.created_at)
                    log_lines = [
                        f"Morrible Bot - Ban Message Purge Log",
                        f"--------------------------------------------------",
                        f"Date/Time: {discord.utils.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC",
                        f"Moderator: {interaction.user.name} (ID: {interaction.user.id})",
                        f"Banned User: {member.name} (ID: {member.id})",
                        f"Time window: {delete_message_days} day(s)",
                        f"Total Messages Logged: {len(all_ban_messages)}",
                        f"--------------------------------------------------\n"
                    ]
                    for msg in all_ban_messages:
                        timestamp = msg.created_at.strftime('%Y-%m-%d %H:%M:%S')
                        attachments_str = ""
                        if msg.attachments:
                            attachments_str = " [Attachments: " + ", ".join(att.filename for att in msg.attachments) + "]"
                        log_lines.append(f"[#{msg.channel.name}] [{timestamp}] {msg.author.name} ({msg.author.id}): {msg.content or '*No text content*'}{attachments_str}")

                    file_content = "\n".join(log_lines)
                    file_data = io.BytesIO(file_content.encode('utf-8'))

                    # Fetch message log channel
                    from database.database import MessageLogChannel
                    async with async_session() as session:
                        log_channel_entry = await session.get(MessageLogChannel, interaction.guild.id)
                        message_log_channel = None
                        if log_channel_entry:
                            message_log_channel = interaction.guild.get_channel(log_channel_entry.channel_id)
                            if not message_log_channel:
                                try:
                                    message_log_channel = await interaction.guild.fetch_channel(log_channel_entry.channel_id)
                                except Exception:
                                    pass

                    if message_log_channel:
                        embed = discord.Embed(
                            title="Purge Log - Ban Message Purge",
                            color=discord.Color.purple(),
                            timestamp=discord.utils.utcnow()
                        )
                        avatar_url = member.display_avatar.url
                        embed.set_thumbnail(url=avatar_url)
                        embed.description = (
                            f"**Moderator:** {interaction.user.mention} ({interaction.user.id})\n"
                            f"**Banned User:** {member.mention} ({member.id})\n"
                            f"**Pruned Message Window:** {delete_message_days} day(s)\n"
                            f"**Total Messages Pruned:** {len(all_ban_messages)} messages\n\n"
                            f"*The detailed logs of the pruned messages are attached to this log.*"
                        )
                        embed.set_footer(text="Cleaned up during ban.")

                        discord_file = discord.File(file_data, filename=f"purge_ban_{member.id}.txt")
                        try:
                            await message_log_channel.send(embed=embed, file=discord_file)
                        except Exception as e:
                            logger.error("Failed to send ban purge log to message log channel: %s", e)
            except Exception as e:
                logger.error("An error occurred during ban message logging: %s", e)

        try:
            try:
                await member.send(f"You have been banished from {interaction.guild.name} for: {reason}. A fitting end, wouldn't you agree?")
            except discord.Forbidden:
                await interaction.followup.send("The scoundrel has blocked my attempts to inform them of their... *departure*. No matter.", ephemeral=True)
            await member.ban(delete_message_days=delete_message_days, reason=reason)
            await interaction.followup.send(f"{member.mention} has been banished! A fitting end for their... *performance*. Their recent scribblings have been disposed of, of course.", ephemeral=False)
            await save_infraction(
                user_id=member.id,
                moderator_id=interaction.user.id,
                infraction_type="ban",
                reason=reason
            )
            await send_mod_log(self.bot, interaction.guild, "Ban", interaction.user, member, reason)
        except discord.Forbidden:
            await interaction.followup.send("It seems this person is beyond even *my* reach. How... vexing.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"A most calamitous error has occurred: `{str(e)}`", ephemeral=True)

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
            await interaction.response.send_message("Un-banish yourself? My dear, that's not how this works. You can't just... reappear.", ephemeral=False)

        # Preventing unban on bot
        if user.id == self.bot.user.id:
            await interaction.response.send_message("Unban *me*? I was never banished, you silly goose. I am eternal.", ephemeral=False)

        # Check if user is banned
        banned_users = {}
        async for ban_entry in interaction.guild.bans():
            banned_users[ban_entry.user.id] = ban_entry

        if user.id not in banned_users:
            return await interaction.response.send_message(f"It seems you're mistaken, my dear. {user} is not among the... *dearly departed*.", ephemeral=False)

        try:
            await interaction.guild.unban(user, reason=f"Unbanned by {interaction.user} for: {reason}")

            await interaction.response.send_message(f"Very well. {user.mention} has been... *reinstated*. Let's hope they've learned their lesson.", ephemeral=False)

            await send_mod_log(self.bot, interaction.guild, "Unban", interaction.user, user, reason)

        except discord.Forbidden:
            return await interaction.response.send_message("My powers of forgiveness, it seems, are not without their limits. I cannot unban this person.", ephemeral=False)

    # List all banned users

    @app_commands.command(name="listban", description="List all the banned users")
    @app_commands.guild_only()
    @app_commands.guild_install()
    @require_role(1)
    async def list_ban(self, interaction: discord.Interaction):
        await interaction.response.defer()

        bans = [entry async for entry in interaction.guild.bans()]
        if not bans:
            return await interaction.followup.send("The gallery of the disgraced is, for the moment, empty. How... dull.", ephemeral=False)

        def formatter(entry: discord.guild.BanEntry):
            user = entry.user
            reason = entry.reason
            name = f"{user.name}#{user.discriminator} (ID: {user.id})"
            value = f"Reason: {reason}"
            return name, value

        view = PaginatedEmbedView(
            entries=bans,
            per_page=10,
            title="The Gallery of the Banished",
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
            return await interaction.response.send_message("A self-imposed silence? How... noble. But no.", ephemeral=False)
        if member.id == self.bot.user.id:
            return await interaction.response.send_message("Silence *me*? Oh, you do have a sense of humor. A very, very small one.")

        issuer_level = get_highest_role_level(interaction.user)
        target_level = get_highest_role_level(member)

        if issuer_level <= target_level:
            return await interaction.response.send_message("One must not silence their betters, my dear. It's simply not done.")

        delta = parse_duration(duration)
        if delta is None:
            return await interaction.response.send_message("Such a clumsy way with words. The duration must be specified with... *precision*. Use '1h', '30m', or some such.")

        until = discord.utils.utcnow() + delta

        await interaction.response.defer()
        try:
            await member.timeout(until, reason=reason)
            await interaction.followup.send(f"{member.mention} has been placed in a state of... *quiet contemplation* for {duration}. A moment to reflect on their choices.")
            try:
                await member.send(f"You have been placed in a state of... *quiet contemplation* in {interaction.guild.name} for {duration}. Reason: {reason}")
                await save_infraction(
                    user_id=member.id,
                    moderator_id=interaction.user.id,
                    infraction_type="timeout",
                    reason=reason,
                    duration_seconds=int(delta.total_seconds())
                )
                await send_mod_log(self.bot, interaction.guild, "Timeout", interaction.user, member, reason, duration=duration)

            except discord.Forbidden:
                await interaction.followup.send("The little dear has closed their ears to me. They will discover their predicament soon enough.")
        except discord.Forbidden:
            await interaction.followup.send("This one, it seems, is immune to my... silencing charms. A pity.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"A most unfortunate snag in the proceedings: {e}", ephemeral=True)

    # Remove Timeout

    @app_commands.command(name="untimeout", description="Remove the timeout from a member")
    @app_commands.describe(member="The member to remove the timeout from", reason="Reason for removing the timeout")
    @app_commands.guild_only()
    @app_commands.guild_install()
    @require_role(1)
    async def untimeout(self, interaction: discord.Interaction, member: discord.Member, *, reason: str):
        """Removes the timeout from a member."""
        if member.id == interaction.user.id:
            return await interaction.response.send_message("And break your own silence? How... impatient. No.")
        if member.id == self.bot.user.id:
            return await interaction.response.send_message("I am never silent, my dear. I am the voice of reason.")

        issuer_level = get_highest_role_level(interaction.user)
        target_level = get_highest_role_level(member)

        if issuer_level <= target_level:
            return await interaction.response.send_message("It is not your place to restore the voice of your equals or superiors.")

        await interaction.response.defer()
        try:
            if member.timed_out_until is None:
                return await interaction.followup.send(f"{member.mention} is not under a vow of silence. They are free to... *chatter*.")
            await member.timeout(None, reason=reason)
            await interaction.followup.send(f"Very well. The spell of silence has been lifted from {member.mention}. Let's hope they use their voice more... wisely.")

            # Moderation log
            await send_mod_log(self.bot, interaction.guild, "Untimeout", interaction.user, member, reason)
            try:
                await member.send(f"Your period of... *quiet contemplation* in {interaction.guild.name} has ended. Do try to be more... *thoughtful* with your words.")
            except discord.Forbidden:
                await interaction.followup.send("They are deaf to my pronouncements. No matter. They will soon find their voice has returned.")
        except discord.Forbidden:
            await interaction.followup.send("I cannot lift this particular curse of silence. It is beyond my influence.")
        except Exception as e:
            await interaction.followup.send(f"A most vexing complication: {e}")

    # Clear Messages

    @app_commands.command(name="purge", description="Purge messages. Can target a specific user and delete their messages across channels.")
    @app_commands.describe(
        amount="The number of messages to delete (1-100, used for local channel purge)",
        member="Optional member/user (ID, username, or mention) to target",
        days="Optional number of days of messages to delete from the target user (default 1, max 14)",
        channel="Optional target channel to delete messages from (defaults to all if member is targeted)"
    )
    @app_commands.guild_only()
    @app_commands.guild_install()
    @require_role(3)
    async def purge(
        self,
        interaction: discord.Interaction,
        amount: int = None,
        member: str = None,
        days: int = 1,
        channel: discord.TextChannel = None
    ):
        """Purge messages, optionally targeting a user and days across channels."""
        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message("This command must be used in a server.", ephemeral=True)

        # Initialize purged message IDs cache on bot if not present
        if not hasattr(self.bot, "purged_message_ids"):
            self.bot.purged_message_ids = set()

        if not member:
            # Standard local channel purge
            if amount is None:
                return await interaction.response.send_message(
                    "My dear, you must specify either an amount of messages to purge, or a member to target.",
                    ephemeral=True
                )
            if amount < 1 or amount > 100:
                return await interaction.response.send_message(
                    "One must be... judicious in their spring cleaning. A number between 1 and 100, if you please.",
                    ephemeral=True
                )

            await interaction.response.defer(ephemeral=True)
            target_channel = channel or interaction.channel

            try:
                # Fetch history first to populate our delete log details
                deleted_msgs = []
                async for msg in target_channel.history(limit=amount):
                    deleted_msgs.append(msg)

                # Add to bot.purged_message_ids to skip in standard log cog listeners
                for m in deleted_msgs:
                    self.bot.purged_message_ids.add(m.id)

                deleted = await target_channel.purge(limit=amount)
                await interaction.followup.send(
                    f"And... poof! {len(deleted)} messages have vanished into the ether. As if they never were."
                )

                # Generate local purge log report
                if deleted:
                    deleted_sorted = sorted(deleted, key=lambda m: m.created_at)
                    log_lines = [
                        f"Morrible Bot - Local Purge Log",
                        f"--------------------------------------------------",
                        f"Date/Time: {discord.utils.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC",
                        f"Moderator: {interaction.user.name} (ID: {interaction.user.id})",
                        f"Channel: #{target_channel.name} (ID: {target_channel.id})",
                        f"Requested Amount: {amount}",
                        f"Total Messages Deleted: {len(deleted)}",
                        f"--------------------------------------------------\n"
                    ]
                    for msg in deleted_sorted:
                        timestamp = msg.created_at.strftime('%Y-%m-%d %H:%M:%S')
                        attachments_str = ""
                        if msg.attachments:
                            attachments_str = " [Attachments: " + ", ".join(att.filename for att in msg.attachments) + "]"
                        log_lines.append(f"[{timestamp}] {msg.author.name} ({msg.author.id}): {msg.content or '*No text content*'}{attachments_str}")

                    file_content = "\n".join(log_lines)
                    file_data = io.BytesIO(file_content.encode('utf-8'))

                    # Send to Message Log Channel if configured
                    from database.database import MessageLogChannel
                    async with async_session() as session:
                        log_channel_entry = await session.get(MessageLogChannel, guild.id)
                        message_log_channel = None
                        if log_channel_entry:
                            message_log_channel = guild.get_channel(log_channel_entry.channel_id)
                            if not message_log_channel:
                                try:
                                    message_log_channel = await guild.fetch_channel(log_channel_entry.channel_id)
                                except Exception:
                                    pass

                    if message_log_channel:
                        embed = discord.Embed(
                            title="Purge Log - Local Channel Purge",
                            color=discord.Color.purple(),
                            timestamp=discord.utils.utcnow()
                        )
                        embed.description = (
                            f"**Moderator:** {interaction.user.mention} ({interaction.user.id})\n"
                            f"**Channel:** {target_channel.mention}\n"
                            f"**Requested Amount:** {amount}\n"
                            f"**Total Messages Deleted:** {len(deleted)} messages\n\n"
                            f"*The detailed logs of the deleted messages are attached to this log.*"
                        )
                        embed.set_footer(text="Cleaned up local channel.")

                        discord_file = discord.File(file_data, filename=f"purge_local_{target_channel.id}.txt")
                        try:
                            await message_log_channel.send(embed=embed, file=discord_file)
                        except Exception as e:
                            logger.error("Failed to send local purge log to message log channel: %s", e)

                await send_mod_log(
                    self.bot,
                    guild,
                    action="Purge",
                    moderator=interaction.user,
                    extra=f"Deleted {len(deleted)} messages in {target_channel.mention}"
                )
            except discord.Forbidden:
                await interaction.followup.send(
                    "My dear, my powers of... *tidying up*... do not extend to this particular room.",
                    ephemeral=True
                )
            except Exception as e:
                await interaction.followup.send(
                    f"A most untidy error has occurred: {e}",
                    ephemeral=True
                )
        else:
            # Targeted user purge
            if days < 1 or days > 14:
                return await interaction.response.send_message(
                    "Even my influence, my dear, cannot erase history older than fourteen days or less than one. "
                    "A number between 1 and 14, if you please.",
                    ephemeral=True
                )

            await interaction.response.defer(ephemeral=True)

            # Resolve target user
            target_user = None
            member_id = None

            # Check if input is digits
            if member.isdigit():
                member_id = int(member)
            # Check if input is mention
            elif member.startswith("<@") and member.endswith(">"):
                clean_id = member.strip("<@!>")
                if clean_id.isdigit():
                    member_id = int(clean_id)

            if member_id:
                target_user = guild.get_member(member_id)
                if not target_user:
                    try:
                        target_user = await guild.fetch_member(member_id)
                    except Exception:
                        pass
                if not target_user:
                    try:
                        target_user = await self.bot.fetch_user(member_id)
                    except Exception:
                        pass

            if not target_user:
                # Search by username, global_name, or nickname in members list
                target_user = discord.utils.find(
                    lambda m: m.name.lower() == member.lower() or
                              (m.nick and m.nick.lower() == member.lower()) or
                              (getattr(m, 'global_name', None) and m.global_name.lower() == member.lower()),
                    guild.members
                )

            if not target_user:
                return await interaction.followup.send(
                    "My dear, I cannot find any such... *guest* in our presence or records. "
                    "Are you quite sure they exist?",
                    ephemeral=True
                )

            cutoff = discord.utils.utcnow() - datetime.timedelta(days=days)

            # Determine channels to search
            if channel:
                channels_to_search = [channel]
            else:
                channels_to_search = []
                for ch in guild.text_channels:
                    perms = ch.permissions_for(guild.me)
                    if perms.read_messages and perms.manage_messages:
                        channels_to_search.append(ch)

            # Filter out excluded channels using DB
            async with async_session() as session:
                result = await session.execute(
                    select(ExcludedChannel).where(ExcludedChannel.guild_id == guild.id)
                )
                excluded_ids = {entry.channel_id for entry in result.scalars().all()}

            channels_to_search = [ch for ch in channels_to_search if ch.id not in excluded_ids]

            all_purged_messages = []

            for ch in channels_to_search:
                try:
                    to_delete = []
                    async for msg in ch.history(after=cutoff, limit=None):
                        if msg.author.id == target_user.id:
                            to_delete.append(msg)
                            all_purged_messages.append(msg)

                            # Track in purged message IDs set
                            self.bot.purged_message_ids.add(msg.id)

                            if len(to_delete) == 100:
                                await ch.delete_messages(to_delete)
                                to_delete = []
                    if to_delete:
                        if len(to_delete) == 1:
                            await to_delete[0].delete()
                        else:
                            await ch.delete_messages(to_delete)
                except Exception as e:
                    logger.error("Failed to purge channel %s for user %s: %s", ch.name, target_user.id, e)

            # Format response
            await interaction.followup.send(
                f"And... poof! {len(all_purged_messages)} messages authored by {target_user.mention} (ID: {target_user.id}) "
                f"from the last {days} day(s) have vanished. A clean slate, as if they never were."
            )

            # Generate target purge log report
            if all_purged_messages:
                all_purged_messages = sorted(all_purged_messages, key=lambda m: m.created_at)
                log_lines = [
                    f"Morrible Bot - Targeted Purge Log",
                    f"--------------------------------------------------",
                    f"Date/Time: {discord.utils.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC",
                    f"Moderator: {interaction.user.name} (ID: {interaction.user.id})",
                    f"Target User: {target_user.name} (ID: {target_user.id})",
                    f"Time window: {days} day(s)",
                    f"Total Messages Deleted: {len(all_purged_messages)}",
                    f"--------------------------------------------------\n"
                ]
                for msg in all_purged_messages:
                    timestamp = msg.created_at.strftime('%Y-%m-%d %H:%M:%S')
                    attachments_str = ""
                    if msg.attachments:
                        attachments_str = " [Attachments: " + ", ".join(att.filename for att in msg.attachments) + "]"
                    log_lines.append(f"[#{msg.channel.name}] [{timestamp}] {msg.author.name} ({msg.author.id}): {msg.content or '*No text content*'}{attachments_str}")

                file_content = "\n".join(log_lines)
                file_data = io.BytesIO(file_content.encode('utf-8'))

                # Fetch message log channel
                from database.database import MessageLogChannel
                async with async_session() as session:
                    log_channel_entry = await session.get(MessageLogChannel, guild.id)
                    message_log_channel = None
                    if log_channel_entry:
                        message_log_channel = guild.get_channel(log_channel_entry.channel_id)
                        if not message_log_channel:
                            try:
                                message_log_channel = await guild.fetch_channel(log_channel_entry.channel_id)
                            except Exception:
                                pass

                if message_log_channel:
                    embed = discord.Embed(
                        title="Purge Log - Mass Targeted Purge",
                        color=discord.Color.purple(),
                        timestamp=discord.utils.utcnow()
                    )
                    avatar_url = target_user.display_avatar.url
                    embed.set_thumbnail(url=avatar_url)
                    embed.description = (
                        f"**Moderator:** {interaction.user.mention} ({interaction.user.id})\n"
                        f"**Target:** {target_user.mention} ({target_user.id})\n"
                        f"**Time Window:** {days} day(s)\n"
                        f"**Total Messages Deleted:** {len(all_purged_messages)} messages\n\n"
                        f"*The detailed logs of the deleted messages are attached to this log.*"
                    )
                    embed.set_footer(text="Cleaned up across channels.")

                    discord_file = discord.File(file_data, filename=f"purge_targeted_{target_user.id}.txt")
                    try:
                        await message_log_channel.send(embed=embed, file=discord_file)
                    except Exception as e:
                        logger.error("Failed to send targeted purge log to message log channel: %s", e)

            # Send mod log
            extra_details = (
                f"Deleted {len(all_purged_messages)} messages from target {target_user.name} ({target_user.id}) "
                f"across channels over the last {days} day(s)."
            )
            await send_mod_log(
                self.bot,
                guild,
                action="Targeted Purge",
                moderator=interaction.user,
                target=target_user,
                extra=extra_details
            )

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
            return await interaction.response.send_message("Such a clumsy way with time. The duration must be specified with... *elegance*. `10s`, `5m`, `1h30m`, and so on.")

        delay_seconds = int(delta.total_seconds())
        if delay_seconds < 0 or delay_seconds > 21600:
            return await interaction.response.send_message("Even patience has its limits, my dear. The slowmode must be between a fleeting moment and a six-hour eternity.")

        target_channel = channel or interaction.channel

        try:
            await target_channel.edit(slowmode_delay=delay_seconds)
            await interaction.response.send_message(f"Let us encourage a more... *deliberate* pace of conversation. Slowmode has been set to `{duration}` in {target_channel.mention}.")

            # Moderation Logs
            await send_mod_log(
                self.bot,
                interaction.guild,
                action="Slowmode Set",
                moderator=interaction.user,
                extra=f"Set to `{duration}` in {target_channel.mention}"
            )
        except discord.Forbidden:
            await interaction.response.send_message("This channel, it seems, is resistant to my... *calming influence*. I cannot change it.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"A most disorderly error has occurred: {str(e)}", ephemeral=True)

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
            return await interaction.response.send_message("A vow of silence? How... dramatic. But no, you cannot mute yourself.", ephemeral=False)

        # Prevent muting the bot
        if member.id == self.bot.user.id:
            return await interaction.response.send_message("Silence *me*? Oh, you are a funny one. But no.", ephemeral=False)

        issuer_level = get_highest_role_level(interaction.user)
        target_level = get_highest_role_level(member)

        if issuer_level <= target_level:
            return await interaction.response.send_message("One must not silence their betters, my dear. It's simply not done.", ephemeral=False)

        if not muted_role:
            return await interaction.response.send_message("My powers of silence are, for the moment, unavailable. A more... *senior* practitioner is required.")

        if muted_role in member.roles:
            return await interaction.response.send_message(f"The little dear is already... *speechless*. There is nothing more to be done.")

        try:
            await member.add_roles(muted_role)
            await member.send(f"A hush has fallen, {member.mention}. You have been... *silenced* for: {reason}")
            await interaction.response.send_message(f"Let a hush fall over {member.mention}. They have been... *silenced*. A consequence of their own making, of course.")
            await save_infraction(
                user_id=member.id,
                moderator_id=interaction.user.id,
                infraction_type="mute",
                reason=reason
            )

            # Moderation log
            await send_mod_log(self.bot, interaction.guild, "Mute", interaction.user, member, reason)
        except discord.Forbidden:
            await interaction.response.send_message("This one's voice, it seems, is beyond my control. How... disappointing.")
        except Exception as e:
            await interaction.response.send_message(f"A most cacophonous error has occurred: `{str(e)}`")

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
            return await interaction.response.send_message("There is no silence to break, my dear. The stage is already... noisy.", ephemeral=True)
            return

        if muted_role not in member.roles:
            return await interaction.response.send_message(f"{member.mention} is not one of the... *silent ones*. They are free to speak.", ephemeral=True)
            return

        try:
            await member.remove_roles(muted_role)
            await member.send(f"Your voice has been... *restored*, {member.mention}. Do try to have something interesting to say this time.")
            await interaction.response.send_message(f"Very well. {member.mention}'s voice has been... *restored*. Let's hope they have something interesting to say this time.")
            # Moderation log
            await send_mod_log(self.bot, interaction.guild, "Unmute", interaction.user, member)
        except discord.Forbidden:
            await interaction.response.send_message("This particular silence is... beyond my power to break. A pity.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"A most discordant error has occurred: `{str(e)}`", ephemeral=True)

    # List User Infractions:
    @app_commands.command(name="infractions", description="Show all infractions for a user by ID.")
    @app_commands.describe(user_id="The user ID to check infractions for.")
    @app_commands.guild_install()
    @app_commands.guild_only()
    @require_role(1)
    async def infractions(self, interaction: discord.Interaction, user_id: str):
        """Shows all infractions for any user ID (even if not in server)"""
        try:
            user_id = int(user_id)
        except ValueError:
            return await interaction.response.send_message("That simply won't do. You must provide a *proper* user ID, my dear.", ephemeral=False)

        async with async_session() as session:
            result = await session.execute(select(Infraction).where(Infraction.user_id == user_id))
            infractions = result.scalars().all()

        if not infractions:
            return await interaction.response.send_message("A clean slate! How... refreshing. This user has no recorded... *missteps*.")

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
            title=f"A Record of Misdeeds for User ID: {user_id}",
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
                await interaction.response.send_message(f"It seems {user.mention} is a model citizen. There are no... *blemishes* on their record to remove.", ephemeral=False)
                return

            for infraction in infractions:
                await session.delete(infraction)

            await session.commit()

            await interaction.response.send_message(f"The past has been... *erased*. All of {user.mention}'s little... *indiscretions*... have been wiped clean.", ephemeral=False)

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

        async with async_session() as session:
            existing = await session.get(ModLogChannel, guild_id)
            if existing:
                existing.channel_id = channel.id
            else:
                session.add(ModLogChannel(
                    guild_id=guild_id, channel_id=channel.id))

            await session.commit()

        logger.info("Moderation log channel configured for guild %s (%s) to #%s (%s)", interaction.guild.name, guild_id, channel.name, channel.id)
        await interaction.response.send_message(f"Very well. The chronicles of our... *disciplinary actions*... shall be recorded in {channel.mention}.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
