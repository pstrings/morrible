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
    @app_commands.guild_install()
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
    @app_commands.guild_install()
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

            ticket_name = f"ticket-{user.name}"
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
    @app_commands.describe(server_name="Name of the server", server_link="Invite link to the server", description="Optional server description", accepted="Whether the partnership was accepted (true/false)")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.guild_only()
    @app_commands.guild_install()
    async def close_ticket(self, interaction: Interaction, server_name: str, server_link: str, accepted: bool, description: str = None):
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

                user = guild.get_member(ticket.user_id)
                closer = interaction.user

                embed = discord.Embed(
                    title="🪪 Partnership Ticket Close"
                    description=f"**Status:** {'Accepted ✅' if accepted else 'Rejected ❌'}"
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

                embed.set_footer(text="Partnership Log")

                # Optional image preview attempt
                if "discord.gg" in server_link or "discord.com/invite" in server_link:
                    # Placeholder image
                    embed.set_thumbnail(
                        url="https://cdn.discordapp.com/embed/avatars/0.png")

                log_channel_id = 1234567890  # REPLACE with actual modlog channel ID
                log_channel = guild.get_channel(log_channel_id)
                if log_channel and isinstance(log_channel, discord.TextChannel):
                    await log_channel.send(embed=embed)

        await interaction.response.send_message("✅ Closing ticket...", ephemeral=True)
        await channel.delete()


async def setup(bot: commands.Bot):
    await bot.add_cog(PartnershipTickets(bot))
