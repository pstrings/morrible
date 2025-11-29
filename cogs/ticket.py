from discord.ext import commands
from discord import app_commands, Interaction, ui, Embed, Member, User, TextChannel, Thread, ButtonStyle, ChannelType
import discord
from sqlalchemy.future import select
from sqlalchemy import update
from database.database import TicketChannel, Ticket, TicketLogChannel, async_session
from typing import Literal, Optional
from cogs.moderation import get_highest_role_level, require_role


async def _get_member_safe(guild, user_id):
    """Try cache first, then fetch the member to ensure mentionable Member when possible."""
    member = None
    try:
        member = guild.get_member(user_id)
    except Exception:
        member = None

    if member is None:
        try:
            member = await guild.fetch_member(user_id)
        except Exception:
            member = None

    return member


class TicketView(ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def create_ticket_thread(self, interaction: Interaction, ticket_type: str):
        user = interaction.user
        guild = interaction.guild

        if guild is None:
            return await interaction.response.send_message("This command must be used in a server.", ephemeral=True)

        async with async_session() as session:
            config = await session.get(TicketChannel, guild.id)
            if not config:
                return await interaction.response.send_message("Oh, you poor, unfortunate soul. It seems the ticketing system is not yet... *fully realized*. You'll have to take it up with the administration.", ephemeral=True)

            result = await session.execute(
                select(Ticket).where(
                    Ticket.guild_id == guild.id,
                    Ticket.user_id == user.id,
                    Ticket.status == "open"
                )
            )

            existing_ticket = result.scalar()
            if existing_ticket:
                return await interaction.response.send_message("Patience, my dear. You already have a ticket open. One simply cannot have *all* of my attention at once.", ephemeral=True)

            base_channel = guild.get_channel(int(config.channel_id))
            if not base_channel or not isinstance(base_channel, TextChannel):
                return await interaction.response.send_message("The designated place for such... *requests*... has vanished or is invalid. How utterly bizarre.", ephemeral=True)

            # Check bot permissions for creating private threads
            bot_member = guild.get_member(self.bot.user.id) or guild.me
            if bot_member is None:
                try:
                    bot_member = await guild.fetch_member(self.bot.user.id)
                except Exception:
                    bot_member = None

            if bot_member:
                perms = base_channel.permissions_for(bot_member)
                if not (perms.create_private_threads or perms.manage_threads):
                    return await interaction.response.send_message("I lack permissions to create private threads in the configured channel. Please grant `Create Private Threads` or `Manage Threads`.", ephemeral=True)

            try:
                thread = await base_channel.create_thread(name=f"{ticket_type}-{user.name}", type=ChannelType.private_thread, invitable=False)
            except discord.Forbidden:
                return await interaction.response.send_message("I cannot create a thread in the configured channel. Please check my permissions.", ephemeral=True)
            except discord.HTTPException as e:
                return await interaction.response.send_message(f"Failed to create a ticket thread: {e}", ephemeral=True)

            new_ticket = Ticket(
                guild_id=guild.id,
                user_id=user.id,
                channel_id=thread.id,
                ticket_type=ticket_type
            )
            session.add(new_ticket)
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                await thread.delete()
                return await interaction.response.send_message("Patience, my dear. You already have a ticket open. One simply cannot have *all* of my attention at once.", ephemeral=True)

            await thread.send(f"So, {user.mention}. You require my attention regarding... *{ticket_type}*. Very well. A member of my staff will be with you shortly. Do try to be... *interesting*.")
            await interaction.response.send_message(f"A private audience has been granted. You may present your case in {thread.mention}.", ephemeral=True)

    @ui.button(label="Support", style=ButtonStyle.primary, custom_id="ticket_support")
    async def support_button(self, interaction: Interaction, button: ui.Button):
        await self.create_ticket_thread(interaction, "Support")

    @ui.button(label="Suggestion", style=ButtonStyle.secondary, custom_id="ticket_suggestion")
    async def suggestion_button(self, interaction: Interaction, button: ui.Button):
        await self.create_ticket_thread(interaction, "Suggestion")

    @ui.button(label="Report", style=ButtonStyle.danger, custom_id="ticket_report")
    async def report_button(self, interaction: Interaction, button: ui.Button):
        await self.create_ticket_thread(interaction, "Report")

    @ui.button(label="Partnership", style=ButtonStyle.success, custom_id="ticket_partnership")
    async def partnership_button(self, interaction: Interaction, button: ui.Button):
        await self.create_ticket_thread(interaction, "Partnership")


class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    ticket_group = app_commands.Group(
        name="ticket", description="Ticket commands")

    @ticket_group.command(name="setup", description="Set the channel where tickets will be created and post the ticket UI.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guild_only()
    async def setup_tickets(self, interaction: Interaction, channel: TextChannel):
        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message("This command must be used in a server.", ephemeral=True)

        async with async_session() as session:
            existing = await session.get(TicketChannel, guild.id)
            if existing:
                existing.channel_id = channel.id
            else:
                session.add(TicketChannel(
                    guild_id=guild.id, channel_id=channel.id))
            await session.commit()

        morrible_message = (
            "Such... *ambition*. If you have a request, a suggestion, a... *grievance*, or even a partnership to propose, you may press the appropriate button. Do not dally.")

        # Respond to interaction first to avoid timeout
        await interaction.response.defer(ephemeral=True)

        try:
            await channel.send(morrible_message, view=TicketView(self.bot))
            await interaction.followup.send(f"The stage is set. The ticketing system is now active in {channel.mention}. Let the... *drama*... begin.", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("My influence, it seems, does not extend to that particular channel. A minor setback.", ephemeral=True)
        except discord.HTTPException as e:
            await interaction.followup.send(f"A most... *unfortunate*... complication has arisen: {e}", ephemeral=True)

    @ticket_group.command(name="closeticket", description="Close the current ticket.")
    @app_commands.guild_only()
    @require_role(1)
    async def close_ticket(self, interaction: Interaction, resolution: str,
                           server_name: Optional[str] = None, server_link: Optional[str] = None, accepted: Optional[bool] = None, ad_message_id: Optional[str] = None, description: Optional[str] = None,
                           action: Optional[Literal['warn', 'timeout', 'ban']] = None, user_to_action: Optional[Member] = None, reason: Optional[str] = None):
        channel = interaction.channel
        guild = interaction.guild

        if guild is None:
            return await interaction.response.send_message("This command must be used in a server.", ephemeral=True)

        if not isinstance(channel, Thread) or not channel.name.startswith(("Support-", "Suggestion-", "Report-", "Partnership-")):
            return await interaction.response.send_message("My dear, you are in the wrong... *venue*. This is not a place for such commands.", ephemeral=True)

        async with async_session() as session:
            result = await session.execute(
                select(Ticket).where(
                    Ticket.guild_id == guild.id,
                    Ticket.channel_id == channel.id,
                    Ticket.status == "open"
                )
            )
            ticket = result.scalar()

            if not ticket:
                return await interaction.response.send_message("The matter is already concluded, or perhaps it was never a matter at all. The ticket is closed.", ephemeral=True)

            # Partnership Ticket
            if ticket.ticket_type == "Partnership":
                if accepted and not ad_message_id:
                    return await interaction.response.send_message("One must follow the proper... *etiquette*. An accepted partnership requires an ad message ID.", ephemeral=True)

                # Update ticket status using raw UPDATE to avoid constraint issues
                update_stmt = update(Ticket).where(Ticket.id == ticket.id).values(
                    status="closed",
                    closed_at=discord.utils.utcnow(),
                    ad_message_id=int(
                        ad_message_id) if accepted and ad_message_id else None
                )
                await session.execute(update_stmt)
                await session.commit()

                user = await _get_member_safe(guild, ticket.user_id)
                closer = interaction.user

                embed = Embed(
                    title="A Partnership Concluded",
                    description=f"**Status:** {'Accepted, with *great* potential' if accepted else 'Rejected, a *pity*'}",
                    color=discord.Color.purple()
                )
                embed.add_field(
                    name="Petitioner", value=user.mention if user else f"<@{ticket.user_id}>", inline=True)
                embed.add_field(name="Adjudicator",
                                value=closer.mention, inline=True)
                embed.add_field(name="Server Name",
                                value=server_name, inline=False)
                embed.add_field(name="Server Link",
                                value=server_link, inline=False)
                if description:
                    embed.add_field(name="Server Description",
                                    value=description, inline=False)
                if accepted and ad_message_id:
                    embed.add_field(name="Ad Message ID",
                                    value=ad_message_id, inline=False)

            # Report Ticket
            elif ticket.ticket_type == "Report":
                if action and user_to_action and reason:
                    moderation_cog = self.bot.get_cog("Moderation")
                    if moderation_cog:
                        if action == "warn":
                            await moderation_cog.warn(interaction, user_to_action, reason=reason)
                        elif action == "timeout":
                            await moderation_cog.timeout(interaction, user_to_action, duration="10m", reason=reason)
                        elif action == "ban":
                            await moderation_cog.ban(interaction, user_to_action, reason=reason)

                # Update ticket status using raw UPDATE to avoid constraint issues
                update_stmt = update(Ticket).where(Ticket.id == ticket.id).values(
                    status="closed",
                    closed_at=discord.utils.utcnow()
                )
                await session.execute(update_stmt)
                await session.commit()

                user = await _get_member_safe(guild, ticket.user_id)
                closer = interaction.user

                embed = Embed(
                    title="A Grievance Addressed",
                    description=f"**Resolution:** {resolution}",
                    color=discord.Color.purple()
                )
                embed.add_field(
                    name="Accuser", value=user.mention if user else f"<@{ticket.user_id}>", inline=True)
                embed.add_field(name="Adjudicator",
                                value=closer.mention, inline=True)
                if action and user_to_action:
                    embed.add_field(
                        name="Action Taken", value=f"A... *correction*... has been administered to {user_to_action.mention}: {action}", inline=False)
                    embed.add_field(name="Justification",
                                    value=reason, inline=False)

            # General Tickets (Support, Suggestion)
            else:
                # Update ticket status using raw UPDATE to avoid constraint issues
                update_stmt = update(Ticket).where(Ticket.id == ticket.id).values(
                    status="closed",
                    closed_at=discord.utils.utcnow()
                )
                await session.execute(update_stmt)
                await session.commit()

                user = await _get_member_safe(guild, ticket.user_id)
                closer = interaction.user

                embed = Embed(
                    title=f"A {ticket.ticket_type} Matter Concluded",
                    description=f"**Resolution:** {resolution}",
                    color=discord.Color.purple()
                )
                embed.add_field(
                    name="Petitioner", value=user.mention if user else f"<@{ticket.user_id}>", inline=True)
                embed.add_field(name="Adjudicator",
                                value=closer.mention, inline=True)

            log_config = await session.get(TicketLogChannel, guild.id)
            if log_config and log_config.channel_id:
                log_channel = guild.get_channel(log_config.channel_id)
                if log_channel and isinstance(log_channel, TextChannel):
                    try:
                        await log_channel.send(embed=embed)
                    except discord.Forbidden:
                        pass
                    except discord.HTTPException:
                        pass

        await interaction.response.send_message("The curtain falls. The matter is concluded. The ticket is closed.", ephemeral=True)
        await channel.delete()

    @app_commands.command(name="setticketlogs", description="Set the channel where ticket close logs will be sent.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guild_only()
    async def set_ticket_logs_channel(self, interaction: Interaction, log_channel: TextChannel):
        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message("This command must be used in a server.", ephemeral=True)

        async with async_session() as session:
            existing = await session.get(TicketLogChannel, guild.id)
            if existing:
                existing.channel_id = log_channel.id
            else:
                session.add(TicketLogChannel(
                    guild_id=guild.id, channel_id=log_channel.id))
            await session.commit()
        await interaction.response.send_message(f"The official records of our... *proceedings*... will now be kept in {log_channel.mention}. How... *official*.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
    bot.add_view(TicketView(bot))
