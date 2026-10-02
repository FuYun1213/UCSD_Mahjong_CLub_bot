"""Additive table registry, hashed entry tokens, active membership and reservations."""
from uuid import uuid4
from datetime import datetime, timedelta
from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column
from .database_models import Base


class ClubTable(Base):
    __tablename__ = "club_tables"
    __table_args__ = (
        UniqueConstraint("scope", "number"),
        CheckConstraint("number > 0"), CheckConstraint("capacity >= 2 AND capacity <= 8"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope: Mapped[str] = mapped_column(String(128), index=True)
    tournament_id: Mapped[str | None] = mapped_column(ForeignKey("tournaments.id"), index=True)
    # Existing score/history table IDs remain unchanged. New tables use their UUID.
    score_table_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    number: Mapped[int] = mapped_column(Integer)
    display_name: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(16), default="open")
    capacity: Mapped[int] = mapped_column(Integer, default=4)
    created_at: Mapped[str] = mapped_column(String(40))
    created_by: Mapped[str] = mapped_column(String(128))
    nfc_configured: Mapped[int] = mapped_column(Integer, default=0)
    nfc_label: Mapped[str] = mapped_column(String(120), default="")


class TableJoinToken(Base):
    __tablename__ = "table_join_tokens"
    __table_args__ = (
        CheckConstraint("purpose IN ('table_landing','seat_join','table_join')"),
        CheckConstraint("(purpose = 'seat_join' AND seat IS NOT NULL AND seat IN ('east','south','west','north')) OR (purpose != 'seat_join' AND seat IS NULL)"),
        Index("uq_active_table_token_landing", "table_id", "channel", "purpose", unique=True,
            sqlite_where=text("revoked_at IS NULL AND seat IS NULL"), postgresql_where=text("revoked_at IS NULL AND seat IS NULL")),
        Index("uq_active_table_token_seat", "table_id", "channel", "purpose", "seat", unique=True,
            sqlite_where=text("revoked_at IS NULL AND seat IS NOT NULL"), postgresql_where=text("revoked_at IS NULL AND seat IS NOT NULL")),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    table_id: Mapped[str] = mapped_column(ForeignKey("club_tables.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    channel: Mapped[str] = mapped_column(String(16))
    purpose: Mapped[str] = mapped_column(String(24), default="table_landing")
    seat: Mapped[str | None] = mapped_column(String(5))
    created_at: Mapped[str] = mapped_column(String(40))
    created_by: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[str | None] = mapped_column(String(40))
    revoked_at: Mapped[str | None] = mapped_column(String(40))
    last_used_at: Mapped[str | None] = mapped_column(String(40))
    use_count: Mapped[int] = mapped_column(Integer, default=0)


class ActiveTableMember(Base):
    __tablename__ = "active_table_members"
    __table_args__ = (
        UniqueConstraint("table_id", "seat", name="uq_active_table_wind"),
        CheckConstraint("seat IS NULL OR seat IN ('east','south','west','north')"),
        CheckConstraint("status = 'active' AND left_at IS NULL"),
    )
    membership_id: Mapped[str] = mapped_column(String(64), default=lambda: str(uuid4()), unique=True)
    seat_version: Mapped[int] = mapped_column(Integer, default=1)
    # A primary key enforces one active table across ordinary and tournament modes.
    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    table_id: Mapped[str] = mapped_column(ForeignKey("club_tables.id"), index=True)
    match_id: Mapped[str] = mapped_column(String(64))
    joined_at: Mapped[str] = mapped_column(String(40))
    join_method: Mapped[str] = mapped_column(String(16))
    added_by_user_id: Mapped[str] = mapped_column(String(128))
    seat: Mapped[str | None] = mapped_column(String(5))
    status: Mapped[str] = mapped_column(String(16), default="active")
    left_at: Mapped[str | None] = mapped_column(String(40))


class TableMembershipEvent(Base):
    __tablename__ = "table_membership_events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    table_id: Mapped[str] = mapped_column(ForeignKey("club_tables.id"), index=True)
    match_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    actor_id: Mapped[str] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(32))
    join_method: Mapped[str] = mapped_column(String(16))
    at: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(Text, default="")
    seat: Mapped[str | None] = mapped_column(String(5))


class TableReservation(Base):
    __tablename__ = "table_reservations"
    __table_args__ = (
        CheckConstraint("end_at > scheduled_at"),
        Index("ix_reservation_session_status", "session_id", "status"),
        Index("ix_reservation_start_status", "scheduled_at", "status"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    table_id: Mapped[str] = mapped_column(ForeignKey("club_tables.id"), index=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    user_name: Mapped[str] = mapped_column(String(128))
    scheduled_at: Mapped[str] = mapped_column(String(40), index=True)
    end_at: Mapped[str] = mapped_column(String(40), default=lambda context:
        (datetime.fromisoformat(context.get_current_parameters()["scheduled_at"].replace("Z", "+00:00"))
         + timedelta(hours=1)).isoformat(timespec="milliseconds"))
    session_id: Mapped[str | None] = mapped_column(ForeignKey("reservation_sessions.id"))
    # None is reserved for legacy rows awaiting an explicit administrator choice.
    plan_kind: Mapped[str] = mapped_column(String(16), default="finite")
    planned_games: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    cancelled_at: Mapped[str | None] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_by: Mapped[str | None] = mapped_column(String(128))
    cancelled_by: Mapped[str | None] = mapped_column(String(128))


class ReservationParticipant(Base):
    __tablename__ = "table_reservation_participants"
    reservation_id: Mapped[str] = mapped_column(ForeignKey("table_reservations.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_name: Mapped[str] = mapped_column(String(128))
    added_at: Mapped[str] = mapped_column(String(40))
    # Stable manual order; NULL retains original scheduled-time ordering.
    queue_position: Mapped[int | None] = mapped_column(Integer)


class TableCommand(Base):
    __tablename__ = "table_commands"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    result_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(40))
