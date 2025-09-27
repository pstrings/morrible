# pylint: disable=not-callable

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, BigInteger, String, DateTime, Text
from sqlalchemy.sql import func

DATABASE_URL = "sqlite+aiosqlite:///./morrible.db"

Base = declarative_base()
engine = create_async_engine(DATABASE_URL, echo=False)

# Use async_sessionmaker instead of sessionmaker for async support
async_session = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


class Infraction(Base):
    """Infraction Class"""

    __tablename__ = "infractions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, nullable=False)
    moderator_id = Column(BigInteger, nullable=False)
    infraction_type = Column(String(20), nullable=False)
    reason = Column(String(500), nullable=False)
    timestamp = Column(DateTime(timezone=True),
                       server_default=func.now())  # Fixed timezone
    duration_seconds = Column(Integer, nullable=True)


class TicketChannel(Base):
    __tablename__ = "ticket_channels"

    guild_id = Column(BigInteger, primary_key=True)
    channel_id = Column(BigInteger, nullable=False)


class PartnershipTicket(Base):
    __tablename__ = "partnership_tickets"

    id = Column(Integer, primary_key=True)
    guild_id = Column(BigInteger, nullable=False)
    user_id = Column(BigInteger, nullable=False)
    channel_id = Column(BigInteger, nullable=False)
    status = Column(String(20), default="open")  # Added length constraint
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    closed_at = Column(DateTime(timezone=True), nullable=True)
    ad_message_id = Column(BigInteger, nullable=True)


class ModLogChannel(Base):
    __tablename__ = "mod_log_channels"

    guild_id = Column(BigInteger, primary_key=True)
    channel_id = Column(BigInteger, nullable=False)


class PartnershipLogChannel(Base):
    __tablename__ = "partner_log_channels"

    guild_id = Column(BigInteger, primary_key=True)
    channel_id = Column(BigInteger, nullable=False)


async def init_db():
    """Initialize Database"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db():
    """Close Database"""
    await engine.dispose()
