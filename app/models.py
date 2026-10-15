import base64
import hashlib
import os
from datetime import datetime, time, timezone

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def address_cipher():
    configured_key = os.getenv("ADDRESS_ENCRYPTION_KEY", "development-only-address-key")
    try:
        return Fernet(configured_key.encode())
    except (ValueError, TypeError):
        derived = base64.urlsafe_b64encode(hashlib.sha256(configured_key.encode()).digest())
        return Fernet(derived)


def utc_now():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    memberships: Mapped[list["Membership"]] = relationship(back_populates="user")


class AuthRateLimit(Base):
    __tablename__ = "auth_rate_limits"

    bucket: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_started: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer)


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(500), default="")
    hobbies: Mapped[str] = mapped_column(String(1000), default="")
    is_private: Mapped[bool] = mapped_column(Boolean, default=False)
    member_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    join_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    memberships: Mapped[list["Membership"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("group_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(16), default="member")
    hobbies: Mapped[str] = mapped_column(String(1000), default="")
    timezone_name: Mapped[str] = mapped_column(String(64), default="UTC")
    broad_location: Mapped[str] = mapped_column(String(160), default="")
    exact_address_ciphertext: Mapped[str] = mapped_column(String(700), default="")
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    travel_radius_km: Mapped[float] = mapped_column(Float, default=25.0, server_default="25")
    allow_places_discovery: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    hide_hobbies: Mapped[bool] = mapped_column(Boolean, default=False)
    hide_availability: Mapped[bool] = mapped_column(Boolean, default=False)
    hide_location: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped[User] = relationship(back_populates="memberships")
    group: Mapped[Group] = relationship(back_populates="memberships")
    windows: Mapped[list["AvailabilityWindow"]] = relationship(cascade="all, delete-orphan")

    @property
    def exact_address(self) -> str:
        if not self.exact_address_ciphertext:
            return ""
        try:
            return address_cipher().decrypt(self.exact_address_ciphertext.encode()).decode()
        except (InvalidToken, ValueError):
            return ""

    @exact_address.setter
    def exact_address(self, value: str):
        self.exact_address_ciphertext = (
            address_cipher().encrypt(value.encode()).decode() if value else ""
        )


class AvailabilityWindow(Base):
    __tablename__ = "availability_windows"

    id: Mapped[int] = mapped_column(primary_key=True)
    membership_id: Mapped[int] = mapped_column(ForeignKey("memberships.id"))
    weekday: Mapped[int] = mapped_column(Integer)  # Monday is 0.
    starts_at: Mapped[time] = mapped_column(Time)
    ends_at: Mapped[time] = mapped_column(Time)


class Place(Base):
    __tablename__ = "places"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    activity_tag: Mapped[str] = mapped_column(String(60), index=True)
    broad_location: Mapped[str] = mapped_column(String(160), default="")
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    description: Mapped[str] = mapped_column(String(300), default="")


class Poll(Base):
    __tablename__ = "polls"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    closes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_option_id: Mapped[int | None] = mapped_column(
        ForeignKey("poll_options.id", name="fk_polls_confirmed_option", use_alter=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    options: Mapped[list["PollOption"]] = relationship(
        back_populates="poll", cascade="all, delete-orphan", foreign_keys="PollOption.poll_id"
    )

    @property
    def deadline(self):
        # SQLite returns naive datetimes; deadlines are always stored as UTC.
        return (
            self.closes_at.replace(tzinfo=timezone.utc)
            if self.closes_at.tzinfo is None
            else self.closes_at
        )

    @property
    def is_closed(self):
        return self.closed_at is not None or utc_now() >= self.deadline

    @property
    def voting_open(self):
        return not self.is_closed and self.confirmed_option_id is None


class PollOption(Base):
    __tablename__ = "poll_options"

    id: Mapped[int] = mapped_column(primary_key=True)
    poll_id: Mapped[int] = mapped_column(ForeignKey("polls.id"))
    activity: Mapped[str] = mapped_column(String(120))
    duration_minutes: Mapped[int] = mapped_column(Integer)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    place_id: Mapped[int | None] = mapped_column(ForeignKey("places.id"), nullable=True)
    google_place_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    available_user_ids: Mapped[str] = mapped_column(String(1000), default="")
    poll: Mapped[Poll] = relationship(back_populates="options", foreign_keys=[poll_id])
    place: Mapped[Place | None] = relationship()

    @property
    def available_ids(self) -> set[int]:
        """Keep the legacy CSV storage detail out of routes and templates."""
        return {int(value) for value in self.available_user_ids.split(",") if value.strip()}

    @available_ids.setter
    def available_ids(self, user_ids):
        self.available_user_ids = ",".join(str(user_id) for user_id in sorted(set(user_ids)))


class Vote(Base):
    __tablename__ = "votes"
    __table_args__ = (UniqueConstraint("option_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    option_id: Mapped[int] = mapped_column(ForeignKey("poll_options.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class RSVP(Base):
    __tablename__ = "rsvps"
    __table_args__ = (UniqueConstraint("option_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    option_id: Mapped[int] = mapped_column(ForeignKey("poll_options.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    response: Mapped[str] = mapped_column(String(16))
