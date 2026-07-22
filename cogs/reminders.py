import datetime
import logging
from typing import Optional

import discord
from discord.ext import commands, tasks
from discord import app_commands
from sqlalchemy import select, delete

from database.database import async_session, Reminder
from utils.reminder_parser import (
    parse_reminder_input,
    get_next_trigger_from_rule,
    parse_duration_to_seconds
)

logger = logging.getLogger("morrible")


class SnoozeSelect(discord.ui.Select):
    """Select menu for choosing snooze durations."""

    def __init__(self, reminder_id: int, message_text: str):
        self.reminder_id = reminder_id
        self.message_text = message_text
        options = [
            discord.SelectOption(label="10 minutes", value="10m", emoji="⏱️", description="Snooze for 10 minutes"),
            discord.SelectOption(label="30 minutes", value="30m", emoji="⏳", description="Snooze for 30 minutes"),
            discord.SelectOption(label="1 hour", value="1h", emoji="⏰", description="Snooze for 1 hour"),
            discord.SelectOption(label="Tomorrow at 9am", value="tomorrow at 9am", emoji="🌅", description="Snooze until tomorrow morning"),
            discord.SelectOption(label="1 day", value="1d", emoji="📅", description="Snooze for 1 day"),
        ]
        super().__init__(placeholder="Choose how long to snooze this reminder...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        snooze_choice = self.values[0]
        now = discord.utils.utcnow()
        next_t, _, _, dur_sec, desc = parse_reminder_input(snooze_choice, now=now)

        if not next_t:
            return await interaction.response.send_message(
                "Oh dear, I couldn't compute that snooze interval.", ephemeral=True
            )

        async with async_session() as session:
            new_snooze = Reminder(
                user_id=interaction.user.id,
                message=f"[Snoozed] {self.message_text}",
                is_continuous=False,
                duration_seconds=dur_sec,
                next_trigger=next_t
            )
            session.add(new_snooze)
            await session.commit()

        ts = int(next_t.timestamp())
        embed = discord.Embed(
            title="💤 Reminder Snoozed",
            description=f"Very well, my dear. I shall whisper this to you again <t:{ts}:R> (at <t:{ts}:F>).",
            color=discord.Color.gold()
        )
        # Disable parent view components
        for item in self.view.children:
            item.disabled = True
        await interaction.response.edit_message(embed=embed, view=self.view)


class SnoozeSelectView(discord.ui.View):
    """View containing the snooze dropdown selection."""

    def __init__(self, reminder_id: int, message_text: str):
        super().__init__(timeout=300)
        self.add_item(SnoozeSelect(reminder_id, message_text))


class ReminderDMView(discord.ui.View):
    """Interactive controls attached to DM reminder notifications."""

    def __init__(self, reminder_id: int, message_text: str, is_continuous: bool, recurrence_rule: Optional[str] = None):
        super().__init__(timeout=None)
        self.reminder_id = reminder_id
        self.message_text = message_text
        self.is_continuous = is_continuous
        self.recurrence_rule = recurrence_rule

        # If not repeating, hide skip button
        if not is_continuous:
            self.remove_item(self.skip_button)

    @discord.ui.button(label="Snooze", style=discord.ButtonStyle.secondary, emoji="💤")
    async def snooze_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        snooze_view = SnoozeSelectView(self.reminder_id, self.message_text)
        await interaction.response.send_message(
            "Select how long you wish to delay this reminder, my dear:",
            view=snooze_view,
            ephemeral=True
        )

    @discord.ui.button(label="Dismiss", style=discord.ButtonStyle.gray, emoji="❌")
    async def dismiss_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        embed = interaction.message.embeds[0] if interaction.message.embeds else None
        if embed:
            embed.set_footer(text="Morrible Reminders — Dismissed")
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Skip Next", style=discord.ButtonStyle.primary, emoji="⏭️")
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        now = discord.utils.utcnow()
        async with async_session() as session:
            stmt = select(Reminder).where(Reminder.id == self.reminder_id)
            res = await session.execute(stmt)
            reminder = res.scalar_one_or_none()

            if not reminder:
                return await interaction.response.send_message(
                    "This recurring reminder no longer exists in my memory, my dear.", ephemeral=True
                )

            next_t = None
            if reminder.recurrence_rule:
                next_t = get_next_trigger_from_rule(reminder.recurrence_rule, reminder.next_trigger + datetime.timedelta(seconds=1))
            elif reminder.duration_seconds > 0:
                next_t = reminder.next_trigger + datetime.timedelta(seconds=reminder.duration_seconds)

            if next_t:
                reminder.next_trigger = next_t
                await session.commit()
                ts = int(next_t.timestamp())
                await interaction.response.send_message(
                    f"Skipped the next occurrence! Your next reminder will be triggered <t:{ts}:R> (at <t:{ts}:F>).",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "Unable to calculate the next trigger time.", ephemeral=True
                )


class ClearRemindersView(discord.ui.View):
    """Confirmation view for clearing all reminders."""

    def __init__(self, user_id: int):
        super().__init__(timeout=60)
        self.user_id = user_id

    @discord.ui.button(label="Yes, Clear All", style=discord.ButtonStyle.danger, emoji="⚠️")
    async def confirm_clear(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This is not your prompt to decide, my dear.", ephemeral=True)

        async with async_session() as session:
            stmt = delete(Reminder).where(Reminder.user_id == self.user_id)
            result = await session.execute(stmt)
            count = result.rowcount
            await session.commit()

        for item in self.children:
            item.disabled = True

        embed = discord.Embed(
            title="🧹 Memory Cleared",
            description=f"Very well. I have erased all **{count}** of your active reminders into oblivion.",
            color=discord.Color.dark_gray()
        )
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def cancel_clear(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This is not your prompt to decide, my dear.", ephemeral=True)

        for item in self.children:
            item.disabled = True

        embed = discord.Embed(
            title="Action Cancelled",
            description="Your reminders remain safe and untouched in my memory.",
            color=discord.Color.blurple()
        )
        await interaction.response.edit_message(embed=embed, view=self)


class Reminders(commands.Cog):
    """Cog for managing and triggering user reminders in DMs."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_reminders.start()

    def cog_unload(self):
        self.check_reminders.cancel()

    def format_seconds(self, seconds: int) -> str:
        """Formats an integer number of seconds into a human-readable duration."""
        if seconds <= 0:
            return "schedule"
        if seconds < 60:
            return f"{seconds}s"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes}m"
        hours = minutes // 60
        if hours < 24:
            rem_min = minutes % 60
            return f"{hours}h {rem_min}m" if rem_min else f"{hours}h"
        days = hours // 24
        rem_hours = hours % 24
        return f"{days}d {rem_hours}h" if rem_hours else f"{days}d"

    @tasks.loop(seconds=10)
    async def check_reminders(self):
        """Periodically checks database for due reminders and sends them."""
        await self.bot.wait_until_ready()
        now = discord.utils.utcnow()

        async with async_session() as session:
            try:
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
                            await session.delete(reminder)
                            continue

                    try:
                        embed = discord.Embed(
                            title="🕰️ A Gentle Reminder",
                            color=discord.Color.blurple(),
                            timestamp=discord.utils.utcnow()
                        )

                        if reminder.is_continuous:
                            rule_desc = f"every {self.format_seconds(reminder.duration_seconds)}" if reminder.duration_seconds > 0 else "on your recurring schedule"
                            embed.description = (
                                f"My dear, here is your recurring reminder:\n\n"
                                f"**{reminder.message}**\n\n"
                                f"*This reminder repeats {rule_desc}.*"
                            )
                        else:
                            embed.description = (
                                f"My dear, here is the reminder you requested:\n\n"
                                f"**{reminder.message}**"
                            )

                        embed.set_footer(text=f"Morrible Reminders • ID: {reminder.id}")
                        view = ReminderDMView(
                            reminder_id=reminder.id,
                            message_text=reminder.message,
                            is_continuous=reminder.is_continuous,
                            recurrence_rule=reminder.recurrence_rule
                        )
                        await user.send(embed=embed, view=view)

                    except discord.Forbidden:
                        logger.warning(
                            f"Unable to send DM reminder to user {reminder.user_id} (DMs closed/blocked). Deleting reminder."
                        )
                        await session.delete(reminder)
                        continue
                    except Exception as e:
                        logger.error(f"Error sending reminder to {reminder.user_id}: {e}")
                        continue

                    # Reschedule or delete
                    if reminder.is_continuous:
                        next_t = None
                        if reminder.recurrence_rule:
                            next_t = get_next_trigger_from_rule(reminder.recurrence_rule, now)
                        elif reminder.duration_seconds > 0:
                            next_t = reminder.next_trigger + datetime.timedelta(seconds=reminder.duration_seconds)
                            while next_t <= now:
                                next_t += datetime.timedelta(seconds=reminder.duration_seconds)

                        if next_t:
                            reminder.next_trigger = next_t
                        else:
                            await session.delete(reminder)
                    else:
                        await session.delete(reminder)

                await session.commit()

            except Exception as e:
                logger.error(f"Error in check_reminders task: {e}")

    reminder_group = app_commands.Group(
        name="reminder",
        description="Commands to set, list, edit, and cancel personal reminders."
    )

    @reminder_group.command(name="set", description="Set a reminder to be sent to your DMs.")
    @app_commands.describe(
        message="What should I remind you about? Keep it relatively brief, my dear.",
        schedule="When or how often? (e.g. '10m', 'tomorrow 3pm', 'every monday at 10am', 'every 2h')",
        continuous="Force this reminder to repeat continuous intervals if set as duration."
    )
    async def set_reminder(
        self,
        interaction: discord.Interaction,
        message: str,
        schedule: str,
        continuous: bool = False
    ):
        if len(message) > 500:
            return await interaction.response.send_message(
                "Oh, my dear. That is a novel, not a reminder. Please keep your message under 500 characters.",
                ephemeral=True
            )

        now = discord.utils.utcnow()
        next_t, is_cont, rule, dur_sec, desc = parse_reminder_input(
            schedule, is_continuous_override=continuous, now=now
        )

        if not next_t:
            return await interaction.response.send_message(
                "Oh, my dear, what a preposterous schedule. I can parse relative times ('10m', '2h'), dates ('tomorrow at 3pm', '2026-08-01 15:30'), or repeating schedules ('every monday at 10am', 'every 2h').",
                ephemeral=True
            )

        if not is_cont and (next_t - now).total_seconds() < 10:
            return await interaction.response.send_message(
                "My patience has its limits, and so does my scheduling. A reminder must be at least 10 seconds in the future, my dear.",
                ephemeral=True
            )

        if is_cont and dur_sec > 0 and dur_sec < 300 and not rule.startswith("DAYS:"):
            return await interaction.response.send_message(
                "A continuous reminder must have an interval of at least 5 minutes. I simply refuse to pester you any more frequently than that.",
                ephemeral=True
            )

        async with async_session() as session:
            stmt = select(Reminder).where(Reminder.user_id == interaction.user.id)
            result = await session.execute(stmt)
            active_count = len(result.scalars().all())

            if active_count >= 20:
                return await interaction.response.send_message(
                    "You have reached your limit of active reminders. Even my vast memory cannot cope with more of your endless requests.",
                    ephemeral=True
                )

            new_reminder = Reminder(
                user_id=interaction.user.id,
                message=message,
                is_continuous=is_cont,
                duration_seconds=dur_sec,
                recurrence_rule=rule,
                next_trigger=next_t
            )

            session.add(new_reminder)
            await session.commit()

        ts = int(next_t.timestamp())
        rel_time = f"<t:{ts}:R>"
        abs_time = f"<t:{ts}:F>"
        mode_str = f"repeating ({desc})" if is_cont else f"one-time ({desc})"

        await interaction.response.send_message(
            f"Very well. I have set a **{mode_str}** reminder for you:\n"
            f"📝 *\"{message}\"*\n"
            f"⏰ I shall whisper this in your DMs {rel_time} (at {abs_time}).",
            ephemeral=True
        )

    @reminder_group.command(name="list", description="List all of your active reminders.")
    async def list_reminders(self, interaction: discord.Interaction):
        async with async_session() as session:
            stmt = select(Reminder).where(Reminder.user_id == interaction.user.id).order_by(Reminder.next_trigger.asc())
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
            
            if reminder.recurrence_rule and reminder.recurrence_rule.startswith("DAYS:"):
                rule_str = " (weekly schedule)"
            elif reminder.is_continuous and reminder.duration_seconds > 0:
                rule_str = f" every {self.format_seconds(reminder.duration_seconds)}"
            else:
                rule_str = ""

            short_msg = reminder.message
            if len(short_msg) > 60:
                short_msg = short_msg[:57] + "..."

            embed.add_field(
                name=f"ID: `{reminder.id}` | {mode}{rule_str}",
                value=f"**Message:** {short_msg}\n**Next Trigger:** <t:{ts}:F> (<t:{ts}:R>)",
                inline=False
            )

        embed.set_footer(text="Cancel: /reminder cancel <id> | Edit: /reminder edit <id> | Clear All: /reminder clear")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @reminder_group.command(name="edit", description="Edit an existing reminder's message or schedule.")
    @app_commands.describe(
        reminder_id="The ID of the reminder to edit.",
        message="New reminder message (optional).",
        schedule="New schedule or timing e.g. 'tomorrow 3pm', 'every monday at 10am' (optional)."
    )
    async def edit_reminder(
        self,
        interaction: discord.Interaction,
        reminder_id: int,
        message: Optional[str] = None,
        schedule: Optional[str] = None
    ):
        if not message and not schedule:
            return await interaction.response.send_message(
                "My dear, you must provide either a new `message` or a new `schedule` to edit.",
                ephemeral=True
            )

        if message and len(message) > 500:
            return await interaction.response.send_message(
                "Oh, my dear. That is a novel, not a reminder. Please keep your message under 500 characters.",
                ephemeral=True
            )

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

            if message:
                reminder.message = message

            desc_info = ""
            if schedule:
                now = discord.utils.utcnow()
                next_t, is_cont, rule, dur_sec, desc = parse_reminder_input(
                    schedule, is_continuous_override=reminder.is_continuous, now=now
                )

                if not next_t:
                    return await interaction.response.send_message(
                        "I could not parse that new schedule, my dear. Try formats like '10m', 'tomorrow 3pm', or 'every monday at 10am'.",
                        ephemeral=True
                    )

                reminder.next_trigger = next_t
                reminder.is_continuous = is_cont
                reminder.recurrence_rule = rule
                reminder.duration_seconds = dur_sec
                desc_info = f"\n⏰ New timing: {desc} (<t:{int(next_t.timestamp())}:R>)"

            await session.commit()

        await interaction.response.send_message(
            f"Very well. Reminder `{reminder_id}` has been updated!{desc_info}",
            ephemeral=True
        )

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

    @reminder_group.command(name="clear", description="Clear all of your active reminders.")
    async def clear_reminders(self, interaction: discord.Interaction):
        async with async_session() as session:
            stmt = select(Reminder).where(Reminder.user_id == interaction.user.id)
            result = await session.execute(stmt)
            count = len(result.scalars().all())

        if count == 0:
            return await interaction.response.send_message(
                "You have no active reminders to clear, my dear. How tranquil.",
                ephemeral=True
            )

        embed = discord.Embed(
            title="⚠️ Clear All Reminders",
            description=f"My dear, are you certain you wish to dissolve **all {count}** of your active reminders into the void?",
            color=discord.Color.red()
        )
        view = ClearRemindersView(user_id=interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Reminders(bot))
    print("✅ Loaded Reminders Cog")
