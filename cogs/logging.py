import io
import logging
import discord
from discord.ext import commands
from discord import app_commands, Embed, TextChannel, Member
from database.database import async_session, MemberLogChannel, MessageLogChannel, ExcludedChannel
from cogs.moderation import require_role
from sqlalchemy import select

logger = logging.getLogger("morrible")


class Logging(commands.Cog):
    """Cog for Discord member, role, voice, and message logging with Madame Morrible's style."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _get_log_channel(self, guild: discord.Guild) -> TextChannel | None:
        """Helper to retrieve the configured member log channel for a guild."""
        async with async_session() as session:
            try:
                log_channel_entry = await session.get(MemberLogChannel, guild.id)
            except Exception as e:
                logger.error("Database error while fetching MemberLogChannel for guild %s (%s): %s", guild.name, guild.id, e)
                return None

            if not log_channel_entry:
                logger.debug("No member log channel configured in database for guild %s (%s)", guild.name, guild.id)
                return None

            channel = guild.get_channel(log_channel_entry.channel_id)
            if not channel:
                logger.info("Log channel %s not found in cache for guild %s (%s). Attempting to fetch...", log_channel_entry.channel_id, guild.name, guild.id)
                try:
                    channel = await guild.fetch_channel(log_channel_entry.channel_id)
                except discord.NotFound:
                    logger.error("Log channel %s for guild %s (%s) does not exist (NotFound).", log_channel_entry.channel_id, guild.name, guild.id)
                    return None
                except discord.Forbidden:
                    logger.error("Lacked permission to access/fetch log channel %s for guild %s (%s) (Forbidden).", log_channel_entry.channel_id, guild.name, guild.id)
                    return None
                except Exception as e:
                    logger.error("Failed to fetch log channel %s for guild %s (%s): %s", log_channel_entry.channel_id, guild.name, guild.id, e)
                    return None
            return channel

    async def _get_message_log_channel(self, guild: discord.Guild) -> TextChannel | None:
        """Helper to retrieve the configured message log channel for a guild."""
        async with async_session() as session:
            try:
                log_channel_entry = await session.get(MessageLogChannel, guild.id)
            except Exception as e:
                logger.error("Database error while fetching MessageLogChannel for guild %s (%s): %s", guild.name, guild.id, e)
                return None

            if not log_channel_entry:
                logger.debug("No message log channel configured in database for guild %s (%s)", guild.name, guild.id)
                return None

            channel = guild.get_channel(log_channel_entry.channel_id)
            if not channel:
                logger.info("Log channel %s not found in cache for guild %s (%s). Attempting to fetch...", log_channel_entry.channel_id, guild.name, guild.id)
                try:
                    channel = await guild.fetch_channel(log_channel_entry.channel_id)
                except discord.NotFound:
                    logger.error("Log channel %s for guild %s (%s) does not exist (NotFound).", log_channel_entry.channel_id, guild.name, guild.id)
                    return None
                except discord.Forbidden:
                    logger.error("Lacked permission to access/fetch log channel %s for guild %s (%s) (Forbidden).", log_channel_entry.channel_id, guild.name, guild.id)
                    return None
                except Exception as e:
                    logger.error("Failed to fetch log channel %s for guild %s (%s): %s", log_channel_entry.channel_id, guild.name, guild.id, e)
                    return None
            return channel

    def _get_avatar_url(self, user: discord.abc.User) -> str:
        """Get the user's avatar URL, returning as GIF if animated."""
        if user.display_avatar.is_animated():
            return user.display_avatar.with_format("gif").url
        return user.display_avatar.with_format("png").url

    async def _is_channel_excluded(self, guild_id: int, channel_id: int) -> bool:
        """Check if a channel is in the excluded list."""
        async with async_session() as session:
            entry = await session.get(ExcludedChannel, (guild_id, channel_id))
            return entry is not None

    @commands.Cog.listener()
    async def on_member_join(self, member: Member):
        logger.info("on_member_join event triggered for %s (%s) in guild %s (%s)", member.name, member.id, member.guild.name, member.guild.id)
        channel = await self._get_log_channel(member.guild)
        if not channel:
            logger.debug("on_member_join: Log channel could not be resolved, exiting.")
            return

        created_ts = int(member.created_at.timestamp())
        created_time_str = f"<t:{created_ts}:F> (<t:{created_ts}:R>)"
        avatar_url = self._get_avatar_url(member)

        embed = Embed(
            title="Member Joined",
            color=discord.Color.purple(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_thumbnail(url=avatar_url)
        embed.description = (
            f"**Member:** {member.name} ({member.id})\n"
            f"**Joined Discord:** {created_time_str}"
        )
        embed.set_footer(text="Let us see if they have... *potential*.")

        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            logger.warning("Lacked permission to send member join log in channel %s", channel.id)
        except Exception as e:
            logger.error("Failed to send member join log: %s", e)

    @commands.Cog.listener()
    async def on_member_remove(self, member: Member):
        logger.info("on_member_remove event triggered for %s (%s) in guild %s (%s)", member.name, member.id, member.guild.name, member.guild.id)
        channel = await self._get_log_channel(member.guild)
        if not channel:
            logger.debug("on_member_remove: Log channel could not be resolved, exiting.")
            return

        created_ts = int(member.created_at.timestamp())
        created_time_str = f"<t:{created_ts}:F> (<t:{created_ts}:R>)"
        avatar_url = self._get_avatar_url(member)

        embed = Embed(
            title="Member Left",
            color=discord.Color.purple(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_thumbnail(url=avatar_url)
        embed.description = (
            f"**Member:** {member.name} ({member.id})\n"
            f"**Joined Discord:** {created_time_str}"
        )
        embed.set_footer(text="Alas, they have departed. Perhaps our presence was too... *dramatic*.")

        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            logger.warning("Lacked permission to send member remove log in channel %s", channel.id)
        except Exception as e:
            logger.error("Failed to send member remove log: %s", e)

    @commands.Cog.listener()
    async def on_member_update(self, before: Member, after: Member):
        if before.roles == after.roles:
            return

        channel = await self._get_log_channel(after.guild)
        if not channel:
            return

        added_roles = [role for role in after.roles if role not in before.roles]
        removed_roles = [role for role in before.roles if role not in after.roles]

        created_ts = int(after.created_at.timestamp())
        created_time_str = f"<t:{created_ts}:F> (<t:{created_ts}:R>)"
        avatar_url = self._get_avatar_url(after)

        if added_roles:
            embed = Embed(
                title="Roles added",
                color=discord.Color.purple(),
                timestamp=discord.utils.utcnow()
            )
            embed.set_thumbnail(url=avatar_url)
            roles_str = ", ".join(role.mention for role in added_roles)
            embed.description = (
                f"**Member:** {after.name} ({after.id})\n"
                f"**Joined Discord:** {created_time_str}\n"
                f"**Roles Added:** {roles_str}"
            )
            embed.set_footer(text="A status update. How... *official*.")
            try:
                await channel.send(embed=embed)
            except discord.Forbidden:
                logger.warning("Lacked permission to send role add log in channel %s", channel.id)
            except Exception as e:
                logger.error("Failed to send role add log: %s", e)

        if removed_roles:
            embed = Embed(
                title="Roles removed",
                color=discord.Color.purple(),
                timestamp=discord.utils.utcnow()
            )
            embed.set_thumbnail(url=avatar_url)
            roles_str = ", ".join(role.mention for role in removed_roles)
            embed.description = (
                f"**Member:** {after.name} ({after.id})\n"
                f"**Joined Discord:** {created_time_str}\n"
                f"**Roles Removed:** {roles_str}"
            )
            embed.set_footer(text="A stripping of status. A fall from grace.")
            try:
                await channel.send(embed=embed)
            except discord.Forbidden:
                logger.warning("Lacked permission to send role remove log in channel %s", channel.id)
            except Exception as e:
                logger.error("Failed to send role remove log: %s", e)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: Member, before: discord.VoiceState, after: discord.VoiceState):
        """Log voice or stage channel joins, leaves, and moves."""
        guild = member.guild
        if not guild:
            return

        channel = await self._get_log_channel(guild)
        if not channel:
            return

        # We only care about joins, leaves, or moves
        if before.channel == after.channel:
            return

        # Check if either channel is excluded
        if before.channel and await self._is_channel_excluded(guild.id, before.channel.id):
            return
        if after.channel and await self._is_channel_excluded(guild.id, after.channel.id):
            return

        created_ts = int(member.created_at.timestamp())
        created_time_str = f"<t:{created_ts}:F> (<t:{created_ts}:R>)"
        avatar_url = self._get_avatar_url(member)

        embed = Embed(
            color=discord.Color.purple(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_thumbnail(url=avatar_url)

        # 1. Join voice/stage
        if before.channel is None and after.channel is not None:
            embed.title = "Voice Joined"
            embed.description = (
                f"**Member:** {member.name} ({member.id})\n"
                f"**Joined Discord:** {created_time_str}\n"
                f"**Channel:** {after.channel.mention}"
            )
            embed.set_footer(text="Ah, to make oneself... *heard*.")

        # 2. Leave voice/stage
        elif before.channel is not None and after.channel is None:
            embed.title = "Voice Left"
            embed.description = (
                f"**Member:** {member.name} ({member.id})\n"
                f"**Joined Discord:** {created_time_str}\n"
                f"**Channel:** {before.channel.mention}"
            )
            embed.set_footer(text="Silence has descended once more.")

        # 3. Move voice/stage
        elif before.channel is not None and after.channel is not None:
            embed.title = "Voice Moved"
            embed.description = (
                f"**Member:** {member.name} ({member.id})\n"
                f"**Joined Discord:** {created_time_str}\n"
                f"**From:** {before.channel.mention}\n"
                f"**To:** {after.channel.mention}"
            )
            embed.set_footer(text="Flitting from one room to another... how... *restless*.")

        else:
            return

        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            logger.warning("Lacked permission to send voice log in channel %s", channel.id)
        except Exception as e:
            logger.error("Failed to send voice log: %s", e)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        """Log message deletion (both cached and uncached fallback)."""
        if not payload.guild_id:
            return

        logger.debug("on_raw_message_delete event triggered for message ID %s in guild ID %s", payload.message_id, payload.guild_id)
        # Ignore messages deleted by a bot purge command
        if hasattr(self.bot, "purged_message_ids") and payload.message_id in self.bot.purged_message_ids:
            logger.debug("on_raw_message_delete: ignoring purged message %s", payload.message_id)
            self.bot.purged_message_ids.remove(payload.message_id)
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            logger.debug("on_raw_message_delete: guild ID %s not found in cache. Attempting to fetch...", payload.guild_id)
            try:
                guild = await self.bot.fetch_guild(payload.guild_id)
            except Exception as e:
                logger.error("on_raw_message_delete: Failed to fetch guild ID %s: %s", payload.guild_id, e)
                return

        if await self._is_channel_excluded(payload.guild_id, payload.channel_id):
            logger.debug("on_raw_message_delete: channel ID %s is excluded from logging, skipping log.", payload.channel_id)
            return

        channel = await self._get_message_log_channel(guild)
        if not channel:
            logger.debug("on_raw_message_delete: Log channel could not be resolved, exiting.")
            return

        ch = guild.get_channel(payload.channel_id)
        channel_mention = ch.mention if ch else f"ID: {payload.channel_id}"

        # If the message is cached, we have full details
        if payload.cached_message:
            message = payload.cached_message
            if message.author.bot:
                return

            created_ts = int(message.author.created_at.timestamp())
            created_time_str = f"<t:{created_ts}:F> (<t:{created_ts}:R>)"
            avatar_url = self._get_avatar_url(message.author)

            embed = Embed(
                title="Message Deleted",
                color=discord.Color.purple(),
                timestamp=discord.utils.utcnow()
            )
            embed.set_thumbnail(url=avatar_url)

            content = message.content or "*No text content*"
            if len(content) > 1000:
                content = content[:997] + "..."

            embed.description = (
                f"**Member:** {message.author.name} ({message.author.id})\n"
                f"**Joined Discord:** {created_time_str}\n"
                f"**Channel:** {channel_mention}\n\n"
                f"**Content:** {content}"
            )

            # Manage Attachments / Media / Links
            if message.attachments:
                links = []
                for att in message.attachments:
                    links.append(f"[{att.filename}]({att.url})")
                    # Display preview if it's an image
                    if att.content_type and att.content_type.startswith("image/"):
                        embed.set_image(url=att.url)
                embed.add_field(name="Attachments", value="\n".join(links), inline=False)

            embed.set_footer(text="Gone like a whisper in the wind.")

            try:
                await channel.send(embed=embed)
            except discord.Forbidden:
                logger.warning("Lacked permission to send delete log in channel %s", channel.id)
            except Exception as e:
                logger.error("Failed to send delete log: %s", e)
        else:
            # Fallback for uncached messages
            embed = Embed(
                title="Message Deleted (Uncached)",
                color=discord.Color.purple(),
                timestamp=discord.utils.utcnow()
            )
            embed.description = (
                f"A message (`ID: {payload.message_id}`) was deleted in {channel_mention}.\n"
                f"*Alas, because this message was sent before my memory began to record it, I cannot recall its content.*"
            )
            embed.set_footer(text="Gone like a whisper in the wind.")

            try:
                await channel.send(embed=embed)
            except Exception as e:
                logger.error("Failed to send uncached delete log: %s", e)

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload: discord.RawBulkMessageDeleteEvent):
        """Log bulk message deletion (with group/author file download logic)."""
        if not payload.guild_id:
            return

        logger.debug("on_raw_bulk_message_delete event triggered for %s messages in guild ID %s", len(payload.message_ids), payload.guild_id)
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            logger.debug("on_raw_bulk_message_delete: guild ID %s not found in cache. Attempting to fetch...", payload.guild_id)
            try:
                guild = await self.bot.fetch_guild(payload.guild_id)
            except Exception as e:
                logger.error("on_raw_bulk_message_delete: Failed to fetch guild ID %s: %s", payload.guild_id, e)
                return

        if await self._is_channel_excluded(guild.id, payload.channel_id):
            logger.debug("on_raw_bulk_message_delete: channel ID %s is excluded from logging, skipping log.", payload.channel_id)
            return

        total_ids = set(payload.message_ids)
        if hasattr(self.bot, "purged_message_ids"):
            purged_intersection = total_ids.intersection(self.bot.purged_message_ids)
            if purged_intersection:
                self.bot.purged_message_ids.difference_update(purged_intersection)
                remaining_ids = total_ids - purged_intersection
                if not remaining_ids:
                    return
                cached_messages = [m for m in payload.cached_messages if m.id not in purged_intersection]
                total_count = len(remaining_ids)
            else:
                total_count = len(payload.message_ids)
                cached_messages = payload.cached_messages
        else:
            total_count = len(payload.message_ids)
            cached_messages = payload.cached_messages

        channel = await self._get_message_log_channel(guild)
        if not channel:
            logger.debug("on_raw_bulk_message_delete: Log channel could not be resolved, exiting.")
            return

        ch = guild.get_channel(payload.channel_id)
        channel_mention = ch.mention if ch else f"ID: {payload.channel_id}"

        # Group cached messages by author
        from collections import defaultdict
        user_messages = defaultdict(list)
        for msg in cached_messages:
            if msg.author.bot:
                continue
            user_messages[msg.author].append(msg)

        # Process each author's bulk list
        for author, msgs in user_messages.items():
            if len(msgs) >= 3:
                msgs_sorted = sorted(msgs, key=lambda m: m.created_at)
                log_lines = [
                    f"Bulk Deleted Messages Log",
                    f"User: {author.name} (ID: {author.id})",
                    f"Channel: #{ch.name if ch else 'Unknown'} (ID: {payload.channel_id})",
                    f"Total Cached Messages: {len(msgs)}",
                    f"Time generated: {discord.utils.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC",
                    "--------------------------------------------------\n"
                ]
                for msg in msgs_sorted:
                    timestamp = msg.created_at.strftime('%Y-%m-%d %H:%M:%S')
                    attachments_str = ""
                    if msg.attachments:
                        attachments_str = " [Attachments: " + ", ".join(att.filename for att in msg.attachments) + "]"
                    log_lines.append(f"[{timestamp}] {msg.content or '*No text content*'}{attachments_str}")

                file_content = "\n".join(log_lines)
                file_data = io.BytesIO(file_content.encode('utf-8'))
                discord_file = discord.File(file_data, filename=f"bulk_delete_{author.id}.txt")

                created_ts = int(author.created_at.timestamp())
                created_time_str = f"<t:{created_ts}:F> (<t:{created_ts}:R>)"
                avatar_url = self._get_avatar_url(author)

                embed = Embed(
                    title="Bulk Messages Deleted",
                    color=discord.Color.purple(),
                    timestamp=discord.utils.utcnow()
                )
                embed.set_thumbnail(url=avatar_url)
                embed.description = (
                    f"**Member:** {author.name} ({author.id})\n"
                    f"**Joined Discord:** {created_time_str}\n"
                    f"**Channel:** {channel_mention}\n"
                    f"**Total Deleted (Cached):** {len(msgs)} messages\n\n"
                    f"*The deleted messages have been archived in the attached file.*"
                )
                embed.set_footer(text="A sudden clean up. How... *mysterious*.")

                try:
                    await channel.send(embed=embed, file=discord_file)
                except Exception as e:
                    logger.error("Failed to send bulk delete log: %s", e)
            else:
                # Log them individually
                for msg in msgs:
                    created_ts = int(msg.author.created_at.timestamp())
                    created_time_str = f"<t:{created_ts}:F> (<t:{created_ts}:R>)"
                    avatar_url = self._get_avatar_url(msg.author)

                    embed = Embed(
                        title="Message Deleted",
                        color=discord.Color.purple(),
                        timestamp=discord.utils.utcnow()
                    )
                    embed.set_thumbnail(url=avatar_url)
                    content = msg.content or "*No text content*"
                    if len(content) > 1000:
                        content = content[:997] + "..."

                    embed.description = (
                        f"**Member:** {msg.author.name} ({msg.author.id})\n"
                        f"**Joined Discord:** {created_time_str}\n"
                        f"**Channel:** {channel_mention}\n\n"
                        f"**Content:** {content}"
                    )
                    if msg.attachments:
                        links = []
                        for att in msg.attachments:
                            links.append(f"[{att.filename}]({att.url})")
                            if att.content_type and att.content_type.startswith("image/"):
                                embed.set_image(url=att.url)
                        embed.add_field(name="Attachments", value="\n".join(links), inline=False)

                    embed.set_footer(text="Gone like a whisper in the wind.")
                    try:
                        await channel.send(embed=embed)
                    except Exception as e:
                        logger.error("Failed to send individual delete log from bulk event: %s", e)

        # Summary for uncached messages in bulk delete
        uncached_count = total_count - len(cached_messages)
        if uncached_count > 0:
            embed = Embed(
                title="Bulk Messages Deleted (Uncached)",
                color=discord.Color.purple(),
                timestamp=discord.utils.utcnow()
            )
            embed.description = (
                f"**Total Deleted:** {total_count} messages in {channel_mention}\n"
                f"**Uncached:** {uncached_count} messages\n\n"
                f"*Alas, these {uncached_count} messages were sent before my memory began to record them, "
                f"so I cannot recall their authors or contents.*"
            )
            embed.set_footer(text="A sweeping cleanup. Gone without a trace.")
            try:
                await channel.send(embed=embed)
            except Exception as e:
                logger.error("Failed to send uncached bulk delete log: %s", e)

    @app_commands.command(name="setmemberlog", description="Set the channel where member join, leave, and role logs will be posted.")
    @app_commands.describe(channel="Channel for member logs")
    @app_commands.guild_only()
    @app_commands.guild_install()
    @require_role(3)
    async def set_member_log(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Set channel for member logging"""
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild.id

        async with async_session() as session:
            existing = await session.get(MemberLogChannel, guild_id)
            if existing:
                existing.channel_id = channel.id
            else:
                session.add(MemberLogChannel(guild_id=guild_id, channel_id=channel.id))
            await session.commit()

        logger.info("Member log channel configured for guild %s (%s) to #%s (%s)", interaction.guild.name, guild_id, channel.name, channel.id)
        await interaction.followup.send(
            f"Very well. The coming and going of our... *guests*, and their respective... *elevations*... "
            f"shall be registered in {channel.mention}. How... *observant* of us.",
            ephemeral=True
        )

    @app_commands.command(name="setmessagelog", description="Set the channel where deleted message logs will be posted.")
    @app_commands.describe(channel="Channel for deleted message logs")
    @app_commands.guild_only()
    @app_commands.guild_install()
    @require_role(3)
    async def set_message_log(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Set channel for deleted message logging"""
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild.id

        async with async_session() as session:
            existing = await session.get(MessageLogChannel, guild_id)
            if existing:
                existing.channel_id = channel.id
            else:
                session.add(MessageLogChannel(guild_id=guild_id, channel_id=channel.id))
            await session.commit()

        logger.info("Message log channel configured for guild %s (%s) to #%s (%s)", interaction.guild.name, guild_id, channel.name, channel.id)
        await interaction.followup.send(
            f"Very well. The remnants of... *deleted conversations*... "
            f"shall be registered in {channel.mention}. How... *observant* of us.",
            ephemeral=True
        )

    @app_commands.command(name="logexclude", description="Exclude one or more channels from all logging activities (comma separated).")
    @app_commands.describe(channels="The channels to exclude from logs (Text, Voice, or Stage), separated by commas (mentions, IDs, or names)")
    @app_commands.guild_only()
    @app_commands.guild_install()
    @require_role(3)
    async def log_exclude(self, interaction: discord.Interaction, channels: str):
        """Exclude channels from logs."""
        import re
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild.id

        raw_channels = [c.strip() for c in channels.split(",") if c.strip()]
        if not raw_channels:
            await interaction.followup.send("My dear, you must provide at least one channel.", ephemeral=True)
            return

        excluded_channels = []
        already_excluded = []
        invalid_channels = []

        async with async_session() as session:
            for raw in raw_channels:
                channel = None
                # Check for mention: <#ID>
                match = re.match(r"<#(\d+)>", raw)
                if match:
                    channel_id = int(match.group(1))
                    channel = interaction.guild.get_channel(channel_id)
                elif raw.isdigit():
                    channel_id = int(raw)
                    channel = interaction.guild.get_channel(channel_id)
                else:
                    # Check matching channel by name (case-insensitive)
                    channel = discord.utils.get(interaction.guild.channels, name=raw)
                    if not channel and raw.startswith("#"):
                        channel = discord.utils.get(interaction.guild.channels, name=raw[1:])
                
                if not channel:
                    invalid_channels.append(raw)
                    continue

                existing = await session.get(ExcludedChannel, (guild_id, channel.id))
                if existing:
                    already_excluded.append(channel)
                else:
                    session.add(ExcludedChannel(guild_id=guild_id, channel_id=channel.id))
                    excluded_channels.append(channel)

            await session.commit()

        response_parts = []
        if excluded_channels:
            mentions = ", ".join(c.mention for c in excluded_channels)
            response_parts.append(f"Very well. The secrets of {mentions} shall remain... *untold*. I shall turn a blind eye to their occurrences.")
        if already_excluded:
            mentions = ", ".join(c.mention for c in already_excluded)
            response_parts.append(f"My dear, {mentions} is already kept secret from my eyes.")
        if invalid_channels:
            invalids = ", ".join(f"`{raw}`" for raw in invalid_channels)
            response_parts.append(f"Alas, I could not locate any channel matching: {invalids}. Perhaps you misspoke?")

        await interaction.followup.send("\n".join(response_parts), ephemeral=True)

    @app_commands.command(name="loginclude", description="Re-enable logging for previously excluded channels (comma separated).")
    @app_commands.describe(channels="The channels to include back in logs, separated by commas (mentions, IDs, or names)")
    @app_commands.guild_only()
    @app_commands.guild_install()
    @require_role(3)
    async def log_include(self, interaction: discord.Interaction, channels: str):
        """Remove channels from logging exclusions."""
        import re
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild.id

        raw_channels = [c.strip() for c in channels.split(",") if c.strip()]
        if not raw_channels:
            await interaction.followup.send("My dear, you must provide at least one channel.", ephemeral=True)
            return

        included_channels = []
        not_excluded = []
        invalid_channels = []

        async with async_session() as session:
            for raw in raw_channels:
                channel = None
                # Check for mention: <#ID>
                match = re.match(r"<#(\d+)>", raw)
                if match:
                    channel_id = int(match.group(1))
                    channel = interaction.guild.get_channel(channel_id)
                elif raw.isdigit():
                    channel_id = int(raw)
                    channel = interaction.guild.get_channel(channel_id)
                else:
                    # Check matching channel by name (case-insensitive)
                    channel = discord.utils.get(interaction.guild.channels, name=raw)
                    if not channel and raw.startswith("#"):
                        channel = discord.utils.get(interaction.guild.channels, name=raw[1:])
                
                if not channel:
                    invalid_channels.append(raw)
                    continue

                existing = await session.get(ExcludedChannel, (guild_id, channel.id))
                if not existing:
                    not_excluded.append(channel)
                else:
                    await session.delete(existing)
                    included_channels.append(channel)

            await session.commit()

        response_parts = []
        if included_channels:
            mentions = ", ".join(c.mention for c in included_channels)
            response_parts.append(f"Ah, so {mentions} is returned to the public stage. I shall resume my... *observations*.")
        if not_excluded:
            mentions = ", ".join(c.mention for c in not_excluded)
            response_parts.append(f"My dear, {mentions} was never excluded from my watchful gaze.")
        if invalid_channels:
            invalids = ", ".join(f"`{raw}`" for raw in invalid_channels)
            response_parts.append(f"Alas, I could not locate any channel matching: {invalids}. Perhaps you misspoke?")

        await interaction.followup.send("\n".join(response_parts), ephemeral=True)

    @app_commands.command(name="loglistexcluded", description="List all channels excluded from logging.")
    @app_commands.guild_only()
    @app_commands.guild_install()
    @require_role(3)
    async def log_list_excluded(self, interaction: discord.Interaction):
        """List all excluded channels in this guild."""
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild.id

        async with async_session() as session:
            result = await session.execute(
                select(ExcludedChannel).where(ExcludedChannel.guild_id == guild_id)
            )
            entries = result.scalars().all()

        if not entries:
            await interaction.followup.send(
                "There are no sanctuary channels. My eyes see... *everything*.",
                ephemeral=True
            )
            return

        mentions = []
        for entry in entries:
            ch = interaction.guild.get_channel(entry.channel_id)
            if ch:
                mentions.append(ch.mention)
            else:
                mentions.append(f"`Unknown Channel (ID: {entry.channel_id})`")

        channels_str = ", ".join(mentions)
        await interaction.followup.send(
            f"Here are the sanctuary channels where my eyes do not pry: {channels_str}",
            ephemeral=True
        )

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Cog-level error handler for check failures and other command execution issues."""
        if isinstance(error, app_commands.CheckFailure):
            err_msg = "My dear, you lack the necessary *stature* to command me in such a way."
            if not interaction.response.is_done():
                await interaction.response.send_message(err_msg, ephemeral=True)
            else:
                await interaction.followup.send(err_msg, ephemeral=True)
        else:
            logger.error("An error occurred in Logging cog: %s", error)


async def setup(bot: commands.Bot):
    await bot.add_cog(Logging(bot))
