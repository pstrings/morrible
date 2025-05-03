from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy import Column, Integer, BigInteger, String, DateTime
from sqlalchemy.sql import func

DATABASE_URL = "sqlite+aiosqlite:///./infractions.db"

Base = declarative_base()
engine = create_async_engine(DATABASE_URL, echo=False)
async_session = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False)


class Infraction(Base):
    """Infraction Class"""

    __tablename__ = "infractions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, nullable=False)
    moderator_id = Column(BigInteger, nullable=False)
    infraction_type = Column(String(20), nullable=False)
    reason = Column(String(500), nullable=False)
    timestamp = Column(DateTime(timezone=False), server_default=func.now())
    duration_seconds = Column(Integer, nullable=True)


async def init_db():
    """Initialise Database"""

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db():
    """Close Database"""

    await engine.dispose()
