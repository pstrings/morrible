from discord.ext import commands
from discord import app_commands, Interaction
import discord
from sqlalchemy.future import select
from database.database import TicketChannel, PartnershipTicket, async_session


class PartnershipTickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # Set ticket channel
    @app_commands.command(name="setticketchannel", description="Set the category where tickets will be created.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guild_only()
    async def set_text_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Sets a channel for tickets"""

        async with async_session() as session:
            existing = await session.get(TicketChannel, interaction.guild.id)
            if existing:
                existing.channel_id = channel.id
            else:
                session.add(TicketChannel(
                    guild_id=interaction.guild.id, channel_id=channel.id))
            await session.commit()

        await interaction.response.send_message(f"✅ Ticket channel set to {channel.mention}")

    # Open Tickets

    @app_commands.command(name="openticket", description="Open a partnership ticket.")
    @app_commands.guild_only()
    async def open_ticket(self, interaction: discord.Interaction):
        """To open tickets for partnership"""

        user = interaction.user
        guild = interaction.guild

        async with async_session() as session:
            config = await session.get(TicketChannel, guild.id)
            if not config:
                return await interaction.response.send_message("❌ Ticket system is not set up. Ask an admin.", ephemeral=True)

            # Check if user already has open ticket
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

            # Permissions
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            }

            for role in guild.roles:
                if role.permissions.kick_members or role.permissions.administrator:
                    overwrites[role] = discord.PermissionOverwrite(
                        read_messages=True, send_messages=True)

            ticket_name = f"ticket-{user.name}-{user.discriminator}"
            channel = await guild.create_text_channel(
                name=ticket_name,
                category=base_channel.category if isinstance(
                    base_channel, discord.TextChannel) else None,
                overwrites=overwrites,
                topic=f"Partnership ticket for {user.display_name}"
            )

            new_ticket = PartnershipTicket(
                guild_id=guild.id,
                user_id=user.id,
                channel_id=channel.id
            )
            session.add(new_ticket)
            await session.commit()

            await channel.send(f"🎟️ {user.mention}, thank you for your interest in partnering. A staff member will respond shortly.")
            await interaction.response.send_message(f"✅ Your ticket has been created: {channel.mention}", ephemeral=False)

    # Close Ticket

    @app_commands.command(name="closeticket", description="Close the current ticket.")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def close_ticket(self, interaction: Interaction):
        channel = interaction.channel
        guild = interaction.guild

        if not channel.name.startswith("ticket-"):
            return await interaction.response.send_message("❌ This is not a ticket channel.", ephemeral=True)

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

        await interaction.response.send_message("✅ Closing ticket...", ephemeral=True)
        await channel.delete()


async def setup(bot: commands.Bot):
    await bot.add_cog(PartnershipTickets(bot))
