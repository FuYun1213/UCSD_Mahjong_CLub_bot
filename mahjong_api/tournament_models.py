"""Additive tournament and durable external delivery records in the existing DB."""
from sqlalchemy import Integer, String, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .database_models import Base


class Tournament(Base):
    __tablename__ = "tournaments"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    state_json: Mapped[str] = mapped_column(Text)
    deleted_at: Mapped[str | None] = mapped_column(String(40), index=True)
    deleted_by: Mapped[str | None] = mapped_column(String(128))
    delete_reason: Mapped[str | None] = mapped_column(Text)


class TournamentAudit(Base):
    __tablename__ = "tournament_audit"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tournament_id: Mapped[str] = mapped_column(String(64), index=True)
    actor_id: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(64))
    detail_json: Mapped[str] = mapped_column(Text)


class TournamentRequest(Base):
    __tablename__ = "tournament_requests"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tournament_id: Mapped[str] = mapped_column(String(64))
    fingerprint: Mapped[str] = mapped_column(String(64))


class ExternalDelivery(Base):
    __tablename__ = "external_deliveries"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tournament_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    actor_id: Mapped[str] = mapped_column(String(128), default="")
    canonical_json: Mapped[str] = mapped_column(Text)
    payload_json: Mapped[str] = mapped_column(Text)
    endpoint: Mapped[str] = mapped_column(Text)
    adapter: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32))
    error_code: Mapped[str] = mapped_column(String(64), default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[str] = mapped_column(String(40))
    response_json: Mapped[str] = mapped_column(Text, default="{}")

class TournamentTableSession(Base):
    """One fixed table match. table_id is stable across rounds; id identifies the match."""
    __tablename__ = "tournament_table_sessions"
    __table_args__ = (UniqueConstraint("tournament_id", "round_id", "table_id"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tournament_id: Mapped[str] = mapped_column(ForeignKey("tournaments.id"), index=True)
    round_id: Mapped[str] = mapped_column(String(64), index=True)
    table_id: Mapped[str] = mapped_column(String(64), index=True)
    number: Mapped[int] = mapped_column(Integer)
    roster_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="WAITING_FOR_CHECK_IN")
    time_limit_seconds: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[str | None] = mapped_column(String(40))
    ends_at: Mapped[str | None] = mapped_column(String(40))
    started_by: Mapped[str | None] = mapped_column(String(128))
    generation: Mapped[int] = mapped_column(Integer, default=0)
    legacy: Mapped[int] = mapped_column(Integer, default=0)


class TournamentCheckIn(Base):
    __tablename__ = "tournament_check_ins"
    __table_args__ = (UniqueConstraint("match_id", "player_id", "generation"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tournament_id: Mapped[str] = mapped_column(ForeignKey("tournaments.id"), index=True)
    match_id: Mapped[str] = mapped_column(ForeignKey("tournament_table_sessions.id"), index=True)
    round_id: Mapped[str] = mapped_column(String(64))
    table_id: Mapped[str] = mapped_column(String(64))
    player_id: Mapped[str] = mapped_column(String(128))
    account_id: Mapped[str] = mapped_column(String(128))
    checked_at: Mapped[str] = mapped_column(String(40))
    generation: Mapped[int] = mapped_column(Integer, default=0)


class TournamentPenalty(Base):
    __tablename__ = "tournament_penalties"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tournament_id: Mapped[str] = mapped_column(ForeignKey("tournaments.id"), index=True)
    player_id: Mapped[str] = mapped_column(String(128), index=True)
    amount: Mapped[str] = mapped_column(String(40))  # Exact Decimal; positive deduction.
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40))
    created_by: Mapped[str] = mapped_column(String(128))
    round_id: Mapped[str | None] = mapped_column(String(64))
    match_id: Mapped[str | None] = mapped_column(String(64))
    phase: Mapped[str] = mapped_column(String(16), default="swiss")
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    revoked_at: Mapped[str | None] = mapped_column(String(40))
    revoked_by: Mapped[str | None] = mapped_column(String(128))
    revoke_reason: Mapped[str | None] = mapped_column(Text)
    replaces: Mapped[str | None] = mapped_column(String(64))
