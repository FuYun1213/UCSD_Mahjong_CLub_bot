"""Logical reservation sessions and durable cross-worker scope serialization."""
from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from .database_models import Base


class ReservationScopeLock(Base):
    __tablename__ = "reservation_scope_locks"
    scope: Mapped[str] = mapped_column(String(128), primary_key=True)


class ReservationSession(Base):
    __tablename__ = "reservation_sessions"
    __table_args__ = (
        CheckConstraint("status IN ('active','cancelled')"),
        CheckConstraint("end_at > start_at"),
        Index("ix_reservation_session_table_start_status", "table_id", "start_at", "status"),
        Index("ix_reservation_window", "table_id", "status", "end_at", "start_at", "id"),
        Index("ix_reservation_candidate", "scope", "status", "start_at"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope: Mapped[str] = mapped_column(String(128), index=True)
    table_id: Mapped[str] = mapped_column(ForeignKey("club_tables.id"), index=True)
    start_at: Mapped[str] = mapped_column(String(40))
    end_at: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))
