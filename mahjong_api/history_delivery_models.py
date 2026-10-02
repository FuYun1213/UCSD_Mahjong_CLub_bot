"""Additive initial score revisions and per-target durable history work."""
from sqlalchemy import ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .database_models import Base


class ScoreRecord(Base):
    __tablename__ = "score_records"
    game_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    current_revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(24), default="confirmed")
    created_at: Mapped[str] = mapped_column(String(40))


class ScoreSourceAlias(Base):
    __tablename__ = "score_source_aliases"
    source_kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    game_id: Mapped[str] = mapped_column(ForeignKey("score_records.game_id"), index=True)


class ScoreRevision(Base):
    __tablename__ = "score_revisions"
    __table_args__ = (UniqueConstraint("actor_id", "request_id", "action"),)
    game_id: Mapped[str] = mapped_column(ForeignKey("score_records.game_id"), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    previous_revision: Mapped[int | None] = mapped_column(Integer)
    actor_id: Mapped[str | None] = mapped_column(String(128))
    request_id: Mapped[str | None] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(32), default="initial_confirmation")
    snapshot_json: Mapped[str] = mapped_column(Text)
    payload_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(40))


class ScoreRevisionPlayer(Base):
    __tablename__ = "score_revision_players"
    __table_args__ = (
        ForeignKeyConstraint(["game_id", "revision"], ["score_revisions.game_id", "score_revisions.revision"]),
        UniqueConstraint("game_id", "revision", "player_ref"),
    )
    game_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    wind: Mapped[str] = mapped_column(String(5), primary_key=True)
    player_ref: Mapped[str] = mapped_column(String(160))
    display_name: Mapped[str] = mapped_column(String(128))
    initial_points: Mapped[int] = mapped_column(Integer)
    final_points: Mapped[int] = mapped_column(Integer)


class HistoryWork:
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    game_id: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    channel: Mapped[str] = mapped_column(String(40))
    target_version: Mapped[str] = mapped_column(String(64))
    target_key: Mapped[str] = mapped_column(String(64))
    target_json: Mapped[str] = mapped_column(Text)
    payload_json: Mapped[str] = mapped_column(Text)
    payload_hash: Mapped[str] = mapped_column(String(64))
    depends_on: Mapped[str | None] = mapped_column(String(40))
    projection_generation: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[str] = mapped_column(String(40))
    lease_token: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[str | None] = mapped_column(String(40))
    ack_revision: Mapped[int | None] = mapped_column(Integer)
    result_json: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(64))
    source_priority: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))


class ScoreProjectionJob(HistoryWork, Base):
    __tablename__ = "score_projection_jobs"
    completion_synced: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (
        ForeignKeyConstraint(["game_id", "revision"], ["score_revisions.game_id", "score_revisions.revision"]),
        UniqueConstraint("game_id", "revision", "channel"),
        Index("ix_score_projection_ready", "status", "next_attempt_at", "created_at"),
        Index("ix_score_projection_target_order", "target_key", "source_priority", "created_at", "status"),
        Index("ix_score_projection_completion", "completion_synced", "status", "created_at"),
    )


class ScoreDelivery(HistoryWork, Base):
    __tablename__ = "score_deliveries"
    __table_args__ = (
        ForeignKeyConstraint(["game_id", "revision"], ["score_revisions.game_id", "score_revisions.revision"]),
        UniqueConstraint("game_id", "revision", "channel", "target_version", "projection_generation"),
        Index("ix_score_delivery_ready", "status", "next_attempt_at", "created_at"),
        Index("ix_score_delivery_target_order", "target_key", "source_priority", "created_at", "status"),
    )


class HistoryTargetLease(Base):
    """A durable fence per target; remote APIs still require marker reconciliation."""
    __tablename__ = "score_history_target_leases"
    target_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    lease_token: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[str | None] = mapped_column(String(40))
