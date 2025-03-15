# db.py
from datetime import datetime

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, DeclarativeBase, mapped_column, relationship
from sqlalchemy import Integer, String, DateTime, ForeignKey

from config import DATABASE_URL

engine = create_async_engine(DATABASE_URL, echo=False)
async_sessionmaker = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id = mapped_column(Integer, nullable=True, index=True)
    username = mapped_column(String, nullable=True)
    name = mapped_column(String, nullable=False)
    phone = mapped_column(String, nullable=False)
    address = mapped_column(String, nullable=False)
    organization = mapped_column(String, nullable=True)

    orders = relationship("Order", back_populates="user", lazy="raise")


class Order(Base):
    __tablename__ = "orders"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id = mapped_column(ForeignKey("users.id"))
    status = mapped_column(String, default="Новая", index=True)
    created_at = mapped_column(DateTime, default=datetime.utcnow)
    preferred_time = mapped_column(String, nullable=True)

    completed_at = mapped_column(DateTime, nullable=True, default=None)

    user = relationship("User", back_populates="orders", lazy="raise")


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
