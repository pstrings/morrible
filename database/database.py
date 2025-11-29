# pylint: disable=not-callable

from datetime import datetime
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import Integer, BigInteger, String, DateTime, Text
from sqlalchemy.sql import func

DATABASE_URL = "sqlite+aiosqlite:///./morrible.db"

class Base(DeclarativeBase):
    pass

engine = create_async_engine(DATABASE_URL, echo=False)

# Use async_sessionmaker instead of sessionmaker for async support
async_session = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


class Infraction(Base):
    """Infraction Class"""

    __tablename__ = "infractions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    moderator_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    infraction_type: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                       server_default=func.now())
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)


class TicketChannel(Base):
    """Configuration for which channel tickets are created in"""
    __tablename__ = "ticket_channels"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)


class Ticket(Base):
    """Generic ticket supporting multiple types: Support, Suggestion, Report, Partnership"""
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ticket_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    ad_message_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True)


class TicketLogChannel(Base):
    """Configuration for where ticket close logs are sent"""
    __tablename__ = "ticket_log_channels"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)


class PartnershipTicket(Base):
    __tablename__ = "partnership_tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ad_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class ModLogChannel(Base):
    __tablename__ = "mod_log_channels"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)


class PartnershipLogChannel(Base):
    __tablename__ = "partner_log_channels"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)


async def init_db():
    """Initialize Database"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db():
    """Close Database"""
    await engine.dispose()