"""Durable reservation queue, game allocations, audit and duration summaries."""
from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database_models import Base


class ReservationQueueState(Base):
    __tablename__ = "reservation_queue_state"
    table_id: Mapped[str] = mapped_column(ForeignKey("club_tables.id"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    ordering_json: Mapped[str] = mapped_column(Text, default="[]")
    updated_at: Mapped[str] = mapped_column(String(40))


class ReservationQueueBatch(Base):
    __tablename__ = "reservation_queue_batches"
    __table_args__ = (
        CheckConstraint("status IN ('provisional','notified','started','completed','cancelled')"),
        Index("ix_reservation_queue_batch_table_status", "table_id", "status"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    table_id: Mapped[str] = mapped_column(ForeignKey("club_tables.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="provisional")
    version: Mapped[int] = mapped_column(Integer, default=1)
    predecessor_game_id: Mapped[str | None] = mapped_column(String(64), index=True)
    started_game_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    estimated_start_at: Mapped[str | None] = mapped_column(String(40))
    suggested_start_at: Mapped[str | None] = mapped_column(String(40))
    estimated_end_at: Mapped[str | None] = mapped_column(String(40))
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    prediction_source: Mapped[str | None] = mapped_column(String(32))
    started_at: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))


class ReservationQueueBatchMember(Base):
    __tablename__ = "reservation_queue_batch_members"
    __table_args__ = (
        UniqueConstraint("batch_id", "user_id"),
        UniqueConstraint("batch_id", "position"),
    )
    batch_id: Mapped[str] = mapped_column(ForeignKey("reservation_queue_batches.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    # Keep allocation evidence even if a corrupt/legacy reservation is removed.
    reservation_id: Mapped[str] = mapped_column(String(64))
    user_name: Mapped[str] = mapped_column(String(128))
    position: Mapped[int] = mapped_column(Integer)
    remaining_games_snapshot: Mapped[int | None] = mapped_column(Integer)


class ReservationGameLink(Base):
    __tablename__ = "reservation_game_links"
    __table_args__ = (
        CheckConstraint("status IN ('started','confirmed','void')"),
        Index("ix_reservation_game_link_reservation", "reservation_id", "user_id", "status"),
    )
    game_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    # Keep allocation evidence even if a corrupt/legacy reservation is removed.
    reservation_id: Mapped[str] = mapped_column(String(64))
    batch_id: Mapped[str | None] = mapped_column(ForeignKey("reservation_queue_batches.id"))
    status: Mapped[str] = mapped_column(String(16))
    linked_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))


class ReservationQueueAudit(Base):
    __tablename__ = "reservation_queue_audit"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    table_id: Mapped[str] = mapped_column(ForeignKey("club_tables.id"), index=True)
    actor_id: Mapped[str] = mapped_column(String(128))
    before_json: Mapped[str] = mapped_column(Text)
    after_json: Mapped[str] = mapped_column(Text)
    at: Mapped[str] = mapped_column(String(40))


class ReservationDurationSample(Base):
    __tablename__ = "reservation_duration_samples"
    game_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    duration_seconds: Mapped[int] = mapped_column(Integer)
    recorded_at: Mapped[str] = mapped_column(String(40))


class ReservationDurationSummary(Base):
    __tablename__ = "reservation_duration_summaries"
    scope: Mapped[str] = mapped_column(String(8), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    game_count: Mapped[int] = mapped_column(Integer)
    total_seconds: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[str] = mapped_column(String(40))
