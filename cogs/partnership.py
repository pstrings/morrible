from discord.ext import commands
from discord import app_commands, Interaction
import discord
from sqlalchemy.future import select
from database.database import TicketChannel, PartnershipTicket, PartnershipLogChannel, ArchiveChannel, async_session


class PartnershipTickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="setticketlogs", description="Set the channel where ticket close logs will be sent.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guild_only()
    @app_commands.guild_install()
    async def set_ticket_logs_channel(self, interaction: discord.Interaction, log_channel: discord.TextChannel):
        async with async_session() as session:
            existing = await session.get(PartnershipLogChannel, interaction.guild.id)
            if existing:
                existing.channel_id = log_channel.id
            else:
                session.add(PartnershipLogChannel(
                    guild_id=interaction.guild.id, channel_id=log_channel.id))
            await session.commit()
        await interaction.response.send_message(f"✅ Ticket logs channel set to {log_channel.mention}")

    @app_commands.command(name="setticketchannel", description="Set the category where tickets will be created.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guild_only()
    @app_commands.guild_install()
    async def set_text_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        async with async_session() as session:
            existing = await session.get(TicketChannel, interaction.guild.id)
            if existing:
                existing.channel_id = channel.id
            else:
                session.add(TicketChannel(
                    guild_id=interaction.guild.id, channel_id=channel.id))
            await session.commit()

        await interaction.response.send_message(f"✅ Ticket channel set to {channel.mention}")

    @app_commands.command(name="setarchivechannel", description="Set the text channel where archived ticket threads will be moved.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guild_only()
    @app_commands.guild_install()
    async def set_archive_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        async with async_session() as session:
            existing = await session.get(ArchiveChannel, interaction.guild.id)
            if existing:
                existing.channel_id = channel.id
            else:
                session.add(ArchiveChannel(
                    guild_id=interaction.guild.id, channel_id=channel.id))
            await session.commit()
        await interaction.response.send_message(f"📦 Archive channel set to {channel.mention}")

    @app_commands.command(name="openticket", description="Open a partnership ticket.")
    @app_commands.guild_only()
    @app_commands.guild_install()
    async def open_ticket(self, interaction: discord.Interaction):
        user = interaction.user
        guild = interaction.guild

        async with async_session() as session:
            config = await session.get(TicketChannel, guild.id)
            if not config:
                return await interaction.response.send_message("❌ Ticket system is not set up. Ask an admin.", ephemeral=True)

            result = await session.execute(
                select(PartnershipTicket).where(
                    PartnershipTicket.guild_id == guild.id,
                    PartnershipTicket.user_id == user.id,
                    PartnershipTicket.status == "open"
                )
            )

            existing_ticket = result.scalar()
            if existing_ticket:
                return await interaction.response.send_message("⚠️ You already have an open ticket.", ephemeral=True)

            base_channel = guild.get_channel(config.channel_id)
            if not base_channel:
                return await interaction.response.send_message("⚠️ Ticket base channel/category not found.", ephemeral=True)

            thread = await base_channel.create_thread(name=f"ticket-{user.name}", type=discord.ChannelType.private_thread, invitable=False)

            new_ticket = PartnershipTicket(
                guild_id=guild.id,
                user_id=user.id,
                channel_id=thread.id
            )
            session.add(new_ticket)
            await session.commit()

            await thread.send(f"🎟️ {user.mention}, thank you for your interest in partnering. A staff member will respond shortly.")
            await interaction.response.send_message(f"✅ Your ticket has been created: {thread.mention}", ephemeral=False)

    @app_commands.command(name="closeticket", description="Close the current ticket.")
    @app_commands.describe(server_name="Name of the server", server_link="Invite link to the server", accepted="Whether the partnership was accepted (true/false)", description="Optional server description")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.guild_only()
    @app_commands.guild_install()
    async def close_ticket(self, interaction: Interaction, server_name: str, server_link: str, accepted: bool, description: str = None):
        channel = interaction.channel
        guild = interaction.guild

        if not isinstance(channel, discord.Thread) or not channel.name.startswith("ticket-"):
            return await interaction.response.send_message("❌ This is not a ticket thread.", ephemeral=True)

        async with async_session() as session:
            result = await session.execute(
                select(PartnershipTicket).where(
                    PartnershipTicket.guild_id == guild.id,
                    PartnershipTicket.channel_id == channel.id,
                    PartnershipTicket.status == "open"
                )
            )
            ticket = result.scalar()
            if ticket:
                ticket.status = "closed"
                ticket.closed_at = discord.utils.utcnow()
                await session.commit()

                user = guild.get_member(ticket.user_id)
                closer = interaction.user

                embed = discord.Embed(
                    title="🪪 Partnership Ticket Close",
                    description=f"**Status:** {'Accepted ✅' if accepted else 'Rejected ❌'}",
                    color=discord.Color.purple()
                )

                embed.add_field(
                    name="Opened by", value=user.mention if user else f"<@{ticket.user_id}>", inline=True)
                embed.add_field(name="Closed by",
                                value=closer.mention, inline=True)
                embed.add_field(name="Server Name",
                                value=server_name, inline=False)
                embed.add_field(name="Server Link",
                                value=server_link, inline=False)

                if description:
                    embed.add_field(name="Server Description",
                                    value=description, inline=False)

                embed.set_footer(text=f"Action taken in {guild.name}")
                embed.timestamp = discord.utils.utcnow()

                log_config = await session.get(PartnershipLogChannel, guild.id)
                if log_config and log_config.channel_id:
                    log_channel = guild.get_channel(log_config.channel_id)
                    if log_channel and isinstance(log_channel, discord.TextChannel):
                        await log_channel.send(embed=embed)

                archive_config = await session.get(ArchiveChannel, guild.id)
                if archive_config:
                    archive_channel = guild.get_channel(
                        archive_config.channel_id)
                    if archive_channel and isinstance(archive_channel, discord.TextChannel):
                        await channel.edit(name=f"archived-{channel.name}", reason="Ticket archived")
                        await channel.send(f"📦 Ticket archived to {archive_channel.mention}.")
                        await archive_channel.send(f"🗂️ Archived ticket: {channel.jump_url}")

        await interaction.response.send_message("✅ Ticket closed and archived.", ephemeral=True)

    @app_commands.command(name="deleteticket", description="Permanently delete a ticket thread.")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.guild_only()
    @app_commands.guild_install()
    async def delete_ticket(self, interaction: Interaction):
        channel = interaction.channel
        if not isinstance(channel, discord.Thread) or not channel.name.startswith("ticket-") and not channel.name.startswith("archived-ticket"):
            return await interaction.response.send_message("❌ This is not a ticket thread.", ephemeral=True)

        await interaction.response.send_message("🗑️ Deleting this ticket...", ephemeral=True)
        await channel.delete()


async def setup(bot: commands.Bot):
    await bot.add_cog(PartnershipTickets(bot))
