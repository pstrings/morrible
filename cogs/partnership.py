from discord.ext import commands
from discord import app_commands, Interaction, ui
import discord
from sqlalchemy.future import select
from database.database import TicketChannel, PartnershipTicket, PartnershipLogChannel, async_session


class OpenTicketButton(ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @ui.button(label="Open Ticket", style=discord.ButtonStyle.green, custom_id="open_ticket")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
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
                return await interaction.response.send_message("⚠️ Ticket base channel not found.", ephemeral=True)

            thread = await base_channel.create_thread(name=f"ticket-{user.name}", type=discord.ChannelType.private_thread, invitable=False)

            new_ticket = PartnershipTicket(
                guild_id=guild.id,
                user_id=user.id,
                channel_id=thread.id
            )
            session.add(new_ticket)
            await session.commit()

            await thread.send(f"🎟️ {user.mention}, thank you for your interest in partnering. A staff member will respond shortly.")
            await interaction.response.send_message(f"✅ Your ticket has been created: {thread.mention}", ephemeral=True)


class PartnershipTickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="setticketchannel", description="Set the channel where tickets will be created and post ticket UI.")
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

        morrible_message = ("Ah, how simply *splendiferous*! Should you wish to court favor and engage in distinguished collaboration, "
                            "click below to open a thread where destiny—and perhaps partnership—awaits!")
        try:
            await channel.send(morrible_message, view=OpenTicketButton(self.bot))
        except discord.Forbidden:
            return await interaction.response.send_message("❌ Bot lacks permission to send message in that channel.", ephemeral=True)
        except discord.HTTPException as e:
            return await interaction.response.send_message(f"❌ Failed to send message: {e}", ephemeral=True)

        await interaction.response.send_message(f"✅ Ticket channel set to {channel.mention} and UI posted.")

    @app_commands.command(name="setpartnerlogchannel", description="Set the channel for partnership logs.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guild_only()
    @app_commands.guild_install()
    async def set_partner_log_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        async with async_session() as session:
            existing = await session.get(PartnershipLogChannel, interaction.guild.id)
            if existing:
                existing.channel_id = channel.id
            else:
                session.add(PartnershipLogChannel(
                    guild_id=interaction.guild.id, channel_id=channel.id))
            await session.commit()
        await interaction.response.send_message(f"✅ Partnership log channel set to {channel.mention}.")

    @app_commands.command(name="partnerclose", description="Close the current ticket.")
    @app_commands.describe(server_name="Name of the server", server_link="Invite link to the server", accepted="Whether the partnership was accepted (true/false)", ad_message_id="Message ID of the partner ad (required if accepted)", description="Optional server description")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.guild_only()
    @app_commands.guild_install()
    async def partner_close(self, interaction: Interaction, server_name: str, server_link: str, accepted: bool, ad_message_id: str = None, description: str = None):
        channel = interaction.channel
        guild = interaction.guild

        if not isinstance(channel, discord.Thread) or not channel.name.startswith("ticket-"):
            return await interaction.response.send_message("❌ This is not a ticket thread.", ephemeral=True)

        if accepted and not ad_message_id:
            return await interaction.response.send_message("❌ You must provide the ad message ID if the partnership was accepted.", ephemeral=True)

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
                if accepted:
                    ticket.ad_message_id = int(ad_message_id)
                await session.commit()

                user = guild.get_member(ticket.user_id)
                closer = interaction.user

                embed = discord.Embed(
                    title="🪪 Partnership Ticket Closed",
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
                if accepted and ad_message_id:
                    embed.add_field(name="Ad Message ID",
                                    value=ad_message_id, inline=False)

                embed.set_footer(text=f"Action taken in {guild.name}")
                log_config = await session.get(PartnershipLogChannel, guild.id)
                if log_config and log_config.channel_id:
                    log_channel = guild.get_channel(log_config.channel_id)
                    if log_channel and isinstance(log_channel, discord.TextChannel):
                        await log_channel.send(embed=embed)

        await interaction.response.send_message("✅ Ticket closed and deleted.", ephemeral=True)
        await channel.delete()

    @app_commands.command(name="addpartner", description="Add a partner without opening a ticket.")
    @app_commands.describe(user="The user to add as partner", server_name="Name of the server", server_link="Invite link to the server", ad_message_id="Message ID of the partner ad", description="Optional server description")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.guild_only()
    @app_commands.guild_install()
    async def add_partner(self, interaction: Interaction, user: discord.User, server_name: str, server_link: str, ad_message_id: str, description: str = None):
        guild = interaction.guild

        # Hardcoded partnership channel ID - REPLACE THIS WITH YOUR ACTUAL CHANNEL ID
        # Replace with your actual channel ID
        PARTNERSHIP_CHANNEL_ID = 123456789012345678

        async with async_session() as session:
            # Check if this user already has a partnership record
            result = await session.execute(
                select(PartnershipTicket).where(
                    PartnershipTicket.guild_id == guild.id,
                    PartnershipTicket.user_id == user.id,
                    PartnershipTicket.ad_message_id.isnot(None)
                )
            )
            existing_partner = result.scalar()

            if existing_partner:
                return await interaction.response.send_message("❌ This user already has an active partnership.", ephemeral=True)

            # Create a new partnership record using the hardcoded channel ID
            new_partner = PartnershipTicket(
                guild_id=guild.id,
                user_id=user.id,
                channel_id=PARTNERSHIP_CHANNEL_ID,  # Use the hardcoded channel ID
                status="closed",  # Directly closed since no ticket process
                closed_at=discord.utils.utcnow(),
                ad_message_id=int(ad_message_id)
            )
            session.add(new_partner)
            await session.commit()

            # Create log embed
            embed = discord.Embed(
                title="🤝 Direct Partnership Added",
                description="**Status:** Accepted ✅",
                color=discord.Color.green()
            )
            embed.add_field(name="Partner", value=user.mention, inline=True)
            embed.add_field(name="Added by",
                            value=interaction.user.mention, inline=True)
            embed.add_field(name="Server Name",
                            value=server_name, inline=False)
            embed.add_field(name="Server Link",
                            value=server_link, inline=False)
            if description:
                embed.add_field(name="Server Description",
                                value=description, inline=False)
            embed.add_field(name="Ad Message ID",
                            value=ad_message_id, inline=False)
            embed.set_footer(text=f"Action taken in {guild.name}")
            embed.timestamp = discord.utils.utcnow()

            # Send to log channel
            log_config = await session.get(PartnershipLogChannel, guild.id)
            if log_config and log_config.channel_id:
                log_channel = guild.get_channel(log_config.channel_id)
                if log_channel and isinstance(log_channel, discord.TextChannel):
                    await log_channel.send(embed=embed)

        await interaction.response.send_message(f"✅ Successfully added {user.mention} as a partner.", ephemeral=True)

    @app_commands.command(name="removepartner", description="Remove a partner and delete their ad.")
    @app_commands.describe(user="The user to remove as partner")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.guild_only()
    @app_commands.guild_install()
    async def remove_partner(self, interaction: Interaction, user: discord.User):
        guild = interaction.guild

        async with async_session() as session:
            # Find the partnership record
            result = await session.execute(
                select(PartnershipTicket).where(
                    PartnershipTicket.guild_id == guild.id,
                    PartnershipTicket.user_id == user.id,
                    PartnershipTicket.ad_message_id.isnot(None)
                )
            )
            partner = result.scalar()

            if not partner:
                return await interaction.response.send_message("❌ No active partnership found for this user.", ephemeral=True)

            ad_message_id = partner.ad_message_id

            # Delete the partnership record
            await session.delete(partner)
            await session.commit()

            # Try to delete the ad message
            try:
                log_config = await session.get(PartnershipLogChannel, guild.id)
                if log_config and log_config.channel_id:
                    log_channel = guild.get_channel(log_config.channel_id)
                    if log_channel and isinstance(log_channel, discord.TextChannel):
                        ad_message = await log_channel.fetch_message(ad_message_id)
                        await ad_message.delete()
            except Exception as e:
                print(f"Failed to delete ad message: {e}")

            # Create log embed
            embed = discord.Embed(
                title="🗑️ Partnership Removed",
                description="**Status:** Removed ❌",
                color=discord.Color.red()
            )
            embed.add_field(name="Former Partner",
                            value=user.mention, inline=True)
            embed.add_field(name="Removed by",
                            value=interaction.user.mention, inline=True)
            embed.add_field(name="Ad Message ID",
                            value=ad_message_id, inline=False)
            embed.set_footer(text=f"Action taken in {guild.name}")
            embed.timestamp = discord.utils.utcnow()

            # Send to log channel
            if log_config and log_config.channel_id:
                log_channel = guild.get_channel(log_config.channel_id)
                if log_channel and isinstance(log_channel, discord.TextChannel):
                    await log_channel.send(embed=embed)

        await interaction.response.send_message(f"✅ Successfully removed {user.mention} as a partner and deleted their ad.", ephemeral=True)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        async with async_session() as session:
            result = await session.execute(
                select(PartnershipTicket).where(
                    PartnershipTicket.user_id == member.id,
                    PartnershipTicket.ad_message_id.isnot(None)
                )
            )
            tickets = result.scalars().all()

            for ticket in tickets:
                try:
                    log_config = await session.get(PartnershipLogChannel, member.guild.id)
                    if not log_config:
                        continue

                    log_channel = member.guild.get_channel(
                        log_config.channel_id)
                    if not log_channel:
                        continue

                    ad_message = await log_channel.fetch_message(ticket.ad_message_id)
                    await ad_message.delete()

                    # Remove the partnership record
                    await session.delete(ticket)

                except Exception as e:
                    print(
                        f"Failed to delete ad message for leaving member: {e}")

            await session.commit()


async def setup(bot: commands.Bot):
    await bot.add_cog(PartnershipTickets(bot))
    bot.add_view(OpenTicketButton(bot))
