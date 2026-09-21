"""Durable manual confirmation, idempotency, and explicit wind snapshots."""
from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database_models import Base


class ManualScoreDraft(Base):
    __tablename__ = "manual_score_drafts"
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String(64), unique=True)
    table_id: Mapped[str | None] = mapped_column(ForeignKey("club_tables.id"))
    score_table_id: Mapped[str | None] = mapped_column(String(64))
    match_id: Mapped[str] = mapped_column(String(64))
    uploader_id: Mapped[str] = mapped_column(String(128), index=True)
    created_at: Mapped[str] = mapped_column(String(40))
    played_at: Mapped[str | None] = mapped_column(String(40))
    confirmed_at: Mapped[str | None] = mapped_column(String(40))
    players_json: Mapped[str] = mapped_column(Text)
    scores_json: Mapped[str] = mapped_column(Text)
    roster_json: Mapped[str] = mapped_column(Text)
    result_json: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="review")
    history_synced: Mapped[int] = mapped_column(Integer, default=0)


class ManualScorePlayer(Base):
    __tablename__ = "manual_score_players"
    __table_args__ = (
        UniqueConstraint("draft_id", "user_id"),
        CheckConstraint("seat IN ('east','south','west','north')"),
    )
    draft_id: Mapped[str] = mapped_column(ForeignKey("manual_score_drafts.id"), primary_key=True)
    seat: Mapped[str] = mapped_column(String(5), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("nfc_users.id"))
    user_name: Mapped[str] = mapped_column(String(128))
    final_points: Mapped[int] = mapped_column(Integer)


class ManualScoreRequest(Base):
    __tablename__ = "manual_score_requests"
    request_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    draft_id: Mapped[str] = mapped_column(ForeignKey("manual_score_drafts.id"))
    uploader_id: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[str] = mapped_column(String(40))
