# pylint: disable=not-callable

from datetime import datetime
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base, Mapped, mapped_column
from sqlalchemy import Integer, BigInteger, String, DateTime
from sqlalchemy.sql import func

TICKETS_DATABASE_URL = "sqlite+aiosqlite:///./tickets.db"

Base = declarative_base()
engine = create_async_engine(TICKETS_DATABASE_URL, echo=False)

# Use async_sessionmaker instead of sessionmaker for async support
async_session = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


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


async def init_tickets_db():
    """Initialize Tickets Database"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_tickets_db():
    """Close Tickets Database"""
    await engine.dispose()
