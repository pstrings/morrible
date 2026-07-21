import datetime
import logging
from typing import Optional

import discord
from discord.ext import commands, tasks
from discord import app_commands
from sqlalchemy import select

from database.database import async_session, Reminder
from cogs.moderation import parse_duration

logger = logging.getLogger("morrible")


class Reminders(commands.Cog):
    """Cog for managing and triggering user reminders in DMs."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_reminders.start()

    def cog_unload(self):
        self.check_reminders.cancel()

    def format_seconds(self, seconds: int) -> str:
        """Formats an integer number of seconds into a human-readable duration."""
        if seconds < 60:
            return f"{seconds}s"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes}m"
        hours = minutes // 60
        if hours < 24:
            rem_min = minutes % 60
            if rem_min:
                return f"{hours}h {rem_min}m"
            return f"{hours}h"
        days = hours // 24
        rem_hours = hours % 24
        if rem_hours:
            return f"{days}d {rem_hours}h"
        return f"{days}d"

    @tasks.loop(seconds=10)
    async def check_reminders(self):
        """Periodically checks the database for reminders that are due and sends them."""
        await self.bot.wait_until_ready()
        now = discord.utils.utcnow()

        async with async_session() as session:
            try:
                # Select reminders where the next trigger time has passed
                stmt = select(Reminder).where(Reminder.next_trigger <= now)
                result = await session.execute(stmt)
                due_reminders = result.scalars().all()

                if not due_reminders:
                    return

                for reminder in due_reminders:
                    user = self.bot.get_user(reminder.user_id)
                    if not user:
                        try:
                            user = await self.bot.fetch_user(reminder.user_id)
                        except discord.HTTPException:
                            # User is invalid or cannot be fetched, remove the reminder
                            await session.delete(reminder)
                            continue

                    try:
                        # Construct a stylish embed in character
                        embed = discord.Embed(
                            title="🕰️ A Gentle Reminder",
                            color=discord.Color.blurple(),
                            timestamp=discord.utils.utcnow()
                        )
                        
                        if reminder.is_continuous:
                            embed.description = (
                                f"My dear, here is your recurring reminder:\n\n"
                                f"**{reminder.message}**\n\n"
                                f"*This reminder will repeat every {self.format_seconds(reminder.duration_seconds)}.*"
                            )
                        else:
                            embed.description = (
                                f"My dear, here is the reminder you requested:\n\n"
                                f"**{reminder.message}**"
                            )

                        embed.set_footer(text="Morrible Reminders")
                        await user.send(embed=embed)

                    except discord.Forbidden:
                        # DMs are closed or bot blocked. Delete the reminder.
                        logger.warning(
                            f"Unable to send DM reminder to user {reminder.user_id} (DMs closed/blocked). Deleting reminder."
                        )
                        await session.delete(reminder)
                        continue
                    except Exception as e:
                        logger.error(f"Error sending reminder to {reminder.user_id}: {e}")
                        continue

                    if reminder.is_continuous:
                        # Calculate the next trigger time
                        reminder.next_trigger = reminder.next_trigger + datetime.timedelta(seconds=reminder.duration_seconds)
                        # Advance next_trigger to be in the future to avoid backlog spam if bot was offline
                        while reminder.next_trigger <= discord.utils.utcnow():
                            reminder.next_trigger += datetime.timedelta(seconds=reminder.duration_seconds)
                    else:
                        await session.delete(reminder)

                await session.commit()

            except Exception as e:
                logger.error(f"Error in check_reminders task: {e}")

    reminder_group = app_commands.Group(
        name="reminder",
        description="Commands to set, list, and cancel your personal reminders."
    )

    @reminder_group.command(name="set", description="Set a reminder to be sent to your DMs.")
    @app_commands.describe(
        message="What should I remind you about? Keep it relatively brief, my dear.",
        duration="When or how often should I remind you? (e.g., '10m', '2h', '1d').",
        continuous="Should this reminder repeat indefinitely at this interval?"
    )
    async def set_reminder(
        self,
        interaction: discord.Interaction,
        message: str,
        duration: str,
        continuous: bool = False
    ):
        if len(message) > 500:
            return await interaction.response.send_message(
                "Oh, my dear. That is a novel, not a reminder. Please keep your message under 500 characters.",
                ephemeral=True
            )

        duration_delta = parse_duration(duration)
        if not duration_delta:
            return await interaction.response.send_message(
                "Oh, my dear, what a preposterous duration. I can only parse durations in seconds (s), minutes (m), hours (h), or days (d). E.g., '1h30m' or '5m'.",
                ephemeral=True
            )

        duration_seconds = int(duration_delta.total_seconds())
        if duration_seconds < 10:
            return await interaction.response.send_message(
                "My patience has its limits, and so does my scheduling. A reminder must be at least 10 seconds in the future, my dear.",
                ephemeral=True
            )

        if continuous and duration_seconds < 300:
            return await interaction.response.send_message(
                "A continuous reminder must have an interval of at least 5 minutes. I simply refuse to pester you any more frequently than that.",
                ephemeral=True
            )

        async with async_session() as session:
            # Enforce reminder limit per user
            stmt = select(Reminder).where(Reminder.user_id == interaction.user.id)
            result = await session.execute(stmt)
            active_count = len(result.scalars().all())

            if active_count >= 20:
                return await interaction.response.send_message(
                    "You have reached your limit of active reminders. Even my vast memory cannot cope with more of your endless requests.",
                    ephemeral=True
                )

            next_trigger = discord.utils.utcnow() + duration_delta

            new_reminder = Reminder(
                user_id=interaction.user.id,
                message=message,
                is_continuous=continuous,
                duration_seconds=duration_seconds,
                next_trigger=next_trigger
            )

            session.add(new_reminder)
            await session.commit()

        ts = int(next_trigger.timestamp())
        rel_time = f"<t:{ts}:R>"
        abs_time = f"<t:{ts}:F>"
        mode_str = "continuous (repeating)" if continuous else "one-time"

        await interaction.response.send_message(
            f"Very well. I have set a **{mode_str}** reminder for you:\n"
            f"📝 *\"{message}\"*\n"
            f"⏰ I shall whisper this in your DMs {rel_time} (at {abs_time}).",
            ephemeral=True
        )

    @reminder_group.command(name="list", description="List all of your active reminders.")
    async def list_reminders(self, interaction: discord.Interaction):
        async with async_session() as session:
            stmt = select(Reminder).where(Reminder.user_id == interaction.user.id)
            result = await session.execute(stmt)
            reminders = result.scalars().all()

        if not reminders:
            return await interaction.response.send_message(
                "A clean slate! You have no reminders active. How... tranquil.",
                ephemeral=True
            )

        embed = discord.Embed(
            title="🕰️ Your Active Reminders",
            description="Here are the tasks you've entrusted to my memory. Do try to keep them organized.",
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow()
        )

        for reminder in reminders:
            ts = int(reminder.next_trigger.timestamp())
            mode = "🔄 Repeating" if reminder.is_continuous else "📍 One-time"
            interval_str = f" every {self.format_seconds(reminder.duration_seconds)}" if reminder.is_continuous else ""
            
            # Truncate message in the list display if too long
            short_msg = reminder.message
            if len(short_msg) > 60:
                short_msg = short_msg[:57] + "..."

            embed.add_field(
                name=f"ID: `{reminder.id}` | {mode}{interval_str}",
                value=f"**Message:** {short_msg}\n**Next Trigger:** <t:{ts}:F> (<t:{ts}:R>)",
                inline=False
            )

        embed.set_footer(text="To cancel a reminder, use /reminder cancel <id>")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @reminder_group.command(name="cancel", description="Cancel one of your active reminders.")
    @app_commands.describe(
        reminder_id="The ID of the reminder to cancel. You can find this using /reminder list."
    )
    async def cancel_reminder(self, interaction: discord.Interaction, reminder_id: int):
        async with async_session() as session:
            stmt = select(Reminder).where(
                Reminder.id == reminder_id,
                Reminder.user_id == interaction.user.id
            )
            result = await session.execute(stmt)
            reminder = result.scalar_one_or_none()

            if not reminder:
                return await interaction.response.send_message(
                    "I search my memory, but there is no such reminder under your name. Are you seeing things, my dear?",
                    ephemeral=True
                )

            await session.delete(reminder)
            await session.commit()

        await interaction.response.send_message(
            f"Very well. The reminder with ID `{reminder_id}` has been dissolved into the void. You are on your own now.",
            ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Reminders(bot))
    print("✅ Loaded Reminders Cog")
