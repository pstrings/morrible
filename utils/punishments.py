import discord
import datetime
from typing import Optional
from database.database import async_session
from sqlalchemy import text

# ----------------------
# User infraction tracking
# ----------------------
user_infractions_cache = {}


async def get_user_infractions(user: discord.Member) -> int:
    """Retrieve the total number of infractions for a user from DB or cache."""
    if user.id in user_infractions_cache:
        return user_infractions_cache[user.id]

    try:
        async with async_session() as session:
            # Use text() for raw SQL to avoid SQL injection
            result = await session.execute(
                text("SELECT COUNT(*) FROM infractions WHERE user_id = :uid"),
                {"uid": user.id}
            )
            count = result.scalar() or 0
            user_infractions_cache[user.id] = count
            return count
    except Exception as e:
        print(f"Database error getting infractions: {e}")
        return 0


async def add_infraction(
    user: discord.Member,
    moderator: discord.Member,
    infraction_type: str,
    reason: str,
    duration_seconds: Optional[int] = None
) -> int:
    """Add an infraction for a user and return total infractions."""
    try:
        async with async_session() as session:
            from database.database import Infraction
            infraction = Infraction(
                user_id=user.id,
                moderator_id=moderator.id,
                infraction_type=infraction_type,
                reason=reason,
                duration_seconds=duration_seconds
            )
            session.add(infraction)
            await session.commit()

        # Update cache
        total = await get_user_infractions(user)
        user_infractions_cache[user.id] = total + 1
        return user_infractions_cache[user.id]
    except Exception as e:
        print(f"Database error adding infraction: {e}")
        return 0


async def handle_punishment(
    bot: discord.Client,
    message: discord.Message,
    user: discord.Member,
    mod_cog=None,
    warn_threshold: int = 1,
    timeout_threshold: int = 3,
    ban_threshold: int = 5,
    timeout_duration: int = 600
):
    """Handle user punishments based on infraction count."""
    # Early validation - ensure we have proper context
    if not message.guild:
        print("AutoMod: Cannot handle punishment outside of guild context")
        return 0, "No action (no guild context)"

    # Get a guaranteed Member object for moderator
    moderator: discord.Member

    # First try: bot.user as Member (should work if bot is in the guild)
    if isinstance(bot.user, discord.Member) and bot.user.guild == message.guild:
        moderator = bot.user
    # Second try: guild owner
    elif message.guild.owner:
        moderator = message.guild.owner
    # Last resort: use a system account (0 user ID) - this should never happen
    else:
        # Create a dummy Member object with system ID
        # This is a fallback that should theoretically never be used
        print("AutoMod: Using system account as moderator fallback")
        # We'll use the bot's application ID or 0 as a system account
        system_id = bot.application.id if bot.application else 0
        # This is a hacky fallback - in practice, one of the above should always work
        moderator = message.guild.get_member(
            system_id) or user  # Ultimate fallback to user

    infractions = await get_user_infractions(user)
    next_count = infractions + 1

    action = "No action"
    duration_to_use: Optional[int] = None

    if next_count >= ban_threshold:
        try:
            await user.ban(reason="AutoMod: exceeded ban threshold")
            action = "Banned"
        except discord.Forbidden:
            action = "Ban failed (missing permissions)"
    elif next_count >= timeout_threshold:
        try:
            # Modern discord.py (2.0+)
            timeout_until = discord.utils.utcnow() + datetime.timedelta(seconds=timeout_duration)
            await user.timeout(timeout_until, reason="AutoMod: exceeded timeout threshold")
            action = f"Timed out for {timeout_duration}s"
            duration_to_use = timeout_duration
        except Exception as e:
            print(f"Timeout error: {e}")
            action = "Timeout failed"
    elif next_count >= warn_threshold:
        action = "Warned"

    # Record infraction in DB - moderator is now guaranteed to be Member
    await add_infraction(
        user=user,
        moderator=moderator,  # type: ignore  # We've guaranteed this is Member
        infraction_type="automod",
        reason=message.content,
        duration_seconds=duration_to_use
    )

    return await get_user_infractions(user), action
