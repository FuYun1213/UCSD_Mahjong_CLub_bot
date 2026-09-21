"""Durable per-session notifications; history survives removed reservations."""
from sqlalchemy import CheckConstraint, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .database_models import Base


class DiscordReminder(Base):
    __tablename__ = "reservation_discord_notifications"
    __table_args__ = (
        UniqueConstraint("session_id", "start_at_snapshot", "notification_type", name="uq_discord_session_start_type"),
        CheckConstraint("status IN ('pending','processing','sent','retrying','failed','cancelled')"),
        CheckConstraint("attempt_count >= 0"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Deliberately no cascading FK: deletion must preserve delivery evidence.
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    scope: Mapped[str] = mapped_column(String(128), index=True)
    start_at_snapshot: Mapped[str] = mapped_column(String(40))
    notification_type: Mapped[str] = mapped_column(String(32), default="one_hour")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    scheduled_for: Mapped[str] = mapped_column(String(40), index=True)
    next_attempt_at: Mapped[str] = mapped_column(String(40), index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[str | None] = mapped_column(String(40))
    last_error: Mapped[str | None] = mapped_column(String(80))
    sent_at: Mapped[str | None] = mapped_column(String(40))
    discord_message_id: Mapped[str | None] = mapped_column(String(24))
    claim_token: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[str | None] = mapped_column(String(40))
    delivery_uncertain: Mapped[int] = mapped_column(Integer, default=0)
    send_started_at: Mapped[str | None] = mapped_column(String(40))
    channel_id: Mapped[str | None] = mapped_column(String(24))
    bot_user_id: Mapped[str | None] = mapped_column(String(24))
    nonce: Mapped[str] = mapped_column(String(25), unique=True)
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))


class DiscordReminderThrottle(Base):
    """A conservative shared cooldown, including Discord global 429 limits."""
    __tablename__ = "reservation_discord_throttle"
    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    not_before: Mapped[str] = mapped_column(String(40))
