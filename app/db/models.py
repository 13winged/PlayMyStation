"""SQLAlchemy 2.0 Async модели: users + integrations (мультиаккаунтинг)."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

Provider = Literal["spotify", "yandex", "soundcloud", "lastfm"]
ActiveProvider = Literal["spotify", "yandex", "soundcloud", "lastfm", "all"]

PROVIDERS: tuple[Provider, ...] = ("spotify", "yandex", "soundcloud", "lastfm")


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    active_provider: Mapped[str] = mapped_column(String(20), default="all")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC)
    )

    integrations: Mapped[list[Integration]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )


class Integration(Base):
    __tablename__ = "integrations"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_user_provider"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(20))  # spotify | yandex | soundcloud | lastfm
    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    service_user_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    user: Mapped[User] = relationship(back_populates="integrations")
