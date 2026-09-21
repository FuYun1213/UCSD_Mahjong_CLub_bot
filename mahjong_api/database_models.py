"""SQLAlchemy 2 models. Account IDs are external identities, not local passwords."""

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "nfc_users"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))


class TableState(Base):
    __tablename__ = "nfc_tables"
    slot: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    table_id: Mapped[str] = mapped_column(String(64), unique=True)
    round_no: Mapped[int] = mapped_column(default=1)
    current_match_id: Mapped[str] = mapped_column(String(64), unique=True)
    pending_match_id: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[str] = mapped_column(String(40))
    # UTC ISO strings retain timezone semantics on both SQLite and PostgreSQL.
    started_at: Mapped[str | None] = mapped_column(String(40))
    dirty: Mapped[int] = mapped_column(default=1)


class SeatRecord(Base):
    __tablename__ = "nfc_seats"
    __table_args__ = (CheckConstraint("seat IN ('east','south','west','north')"),)
    table_id: Mapped[str] = mapped_column(ForeignKey("nfc_tables.table_id"), primary_key=True)
    seat: Mapped[str] = mapped_column(String(5), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("nfc_users.id"), unique=True)
    user_name: Mapped[str] = mapped_column(String(128))


class MatchHistory(Base):
    """One immutable match snapshot; MatchPlayer holds the four relational scores."""
    __tablename__ = "nfc_matches"
    __table_args__ = (UniqueConstraint("table_id", "round_no"),)
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(String(64), unique=True)
    table_id: Mapped[str] = mapped_column(ForeignKey("nfc_tables.table_id"))
    round_no: Mapped[int]
    scores_json: Mapped[str] = mapped_column(Text)
    result_json: Mapped[str] = mapped_column(Text)
    started_at: Mapped[str | None] = mapped_column(String(40))
    ended_at: Mapped[str | None] = mapped_column(String(40))
    duration_seconds: Mapped[int | None]
    # Physical wind order is explicit; never infer a wind from ranking position.
    seat_order: Mapped[str] = mapped_column(String(16), default="ESWN")
    source_seat_order: Mapped[str] = mapped_column(String(16), default="ESWN")
    uploader_id: Mapped[str | None] = mapped_column(String(128))
    history_synced: Mapped[int] = mapped_column(default=0)
    clear_synced: Mapped[int] = mapped_column(default=0)


class MatchPlayer(Base):
    __tablename__ = "nfc_match_players"
    __table_args__ = (UniqueConstraint("match_id", "user_id"),)
    match_id: Mapped[str] = mapped_column(ForeignKey("nfc_matches.match_id"), primary_key=True)
    seat: Mapped[str] = mapped_column(String(5), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("nfc_users.id"))
    user_name: Mapped[str] = mapped_column(String(128))
    initial_points: Mapped[int]
    final_points: Mapped[int]
    delta_points: Mapped[int]
    # Store integral point difference; divide by 1000 for the display score.
    source_position: Mapped[int | None]


class ScoreDraft(Base):
    """Invalid/low-confidence OCR survives refresh and never clears the table."""
    __tablename__ = "nfc_score_drafts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    match_id: Mapped[str] = mapped_column(String(64), index=True)
    table_id: Mapped[str] = mapped_column(String(64))
    uploader_id: Mapped[str] = mapped_column(String(128))
    uploader_seat: Mapped[str] = mapped_column(String(5))
    created_at: Mapped[str] = mapped_column(String(40))
    ended_at: Mapped[str] = mapped_column(String(40))
    roster_json: Mapped[str] = mapped_column(Text)
    raw_json: Mapped[str] = mapped_column(Text)
    normalized_json: Mapped[str] = mapped_column(Text)
    issues_json: Mapped[str] = mapped_column(Text)
    photo_sha256: Mapped[str | None] = mapped_column(String(64))
    fingerprint: Mapped[str] = mapped_column(String(64))
    request_key: Mapped[str | None] = mapped_column(String(128), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="review")


class IdempotencyRecord(Base):
    __tablename__ = "nfc_requests"
    request_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    match_id: Mapped[str] = mapped_column(ForeignKey("nfc_matches.match_id"))


class Metadata(Base):
    __tablename__ = "nfc_metadata"
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
