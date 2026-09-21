"""Competition identities are independent of website login accounts."""
from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .database_models import Base


class TournamentParticipant(Base):
    __tablename__ = "tournament_participants"
    __table_args__ = (UniqueConstraint("tournament_id", "normalized_name"),)
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tournament_id: Mapped[str] = mapped_column(ForeignKey("tournaments.id"), index=True)
    participant_type: Mapped[str] = mapped_column(String(24), default="guest")
    name: Mapped[str] = mapped_column(String(128))
    normalized_name: Mapped[str] = mapped_column(String(128))
    user_id: Mapped[str | None] = mapped_column(String(128))
    session_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    session_expires_at: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[str] = mapped_column(String(40))
    created_by: Mapped[str] = mapped_column(String(128))
    merged_into_user_id: Mapped[str | None] = mapped_column(String(128))
    merged_at: Mapped[str | None] = mapped_column(String(40))
    merged_by: Mapped[str | None] = mapped_column(String(128))


class GuestRecovery(Base):
    __tablename__ = "tournament_guest_recovery"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    participant_id: Mapped[str] = mapped_column(ForeignKey("tournament_participants.id"))
    expires_at: Mapped[str] = mapped_column(String(40))
    used_at: Mapped[str | None] = mapped_column(String(40))
