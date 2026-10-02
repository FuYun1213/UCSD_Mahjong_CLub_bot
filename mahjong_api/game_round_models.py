"""Immutable ordinary-game roster and lifecycle, independent of live seats."""
from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database_models import Base


class GameRound(Base):
    __tablename__ = "nfc_game_rounds"
    __table_args__ = (
        CheckConstraint("status IN ('playing','awaiting_score','completed','void')"),
        Index("ix_game_round_table_status", "table_id", "status", "started_at"),
    )

    game_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    table_id: Mapped[str] = mapped_column(ForeignKey("club_tables.id"), index=True)
    score_table_id: Mapped[str] = mapped_column(String(64), index=True)
    round_no: Mapped[int] = mapped_column(Integer)
    # Captured when the fourth player takes a wind. Later seat changes cannot
    # rewrite this game's players, even while its score awaits entry.
    roster_json: Mapped[str] = mapped_column(Text)
    started_at: Mapped[str] = mapped_column(String(40))
    actual_ended_at: Mapped[str | None] = mapped_column(String(40))
    end_time_source: Mapped[str | None] = mapped_column(String(32))
    actual_end_by: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), default="playing", index=True)
    all_last_at: Mapped[str | None] = mapped_column(String(40))
    all_last_by: Mapped[str | None] = mapped_column(String(128))
    successor_batch_id: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))

