"""Consent-based seat swap requests and cross-role pending user claims."""
from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column
from .database_models import Base


class SeatSwapRequest(Base):
    __tablename__ = "seat_swap_requests"
    __table_args__ = (
        CheckConstraint("status IN ('pending','accepted','declined','expired','cancelled','invalidated')"),
        CheckConstraint("requester_user_id != target_user_id"),
        CheckConstraint("requester_seat IN ('east','south','west','north') AND target_seat IN ('east','south','west','north') AND requester_seat != target_seat"),
        Index("uq_pending_seat_swap_pair", "table_id", "pair_key", unique=True,
              sqlite_where=text("status = 'pending'"), postgresql_where=text("status = 'pending'")),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    table_id: Mapped[str] = mapped_column(ForeignKey("club_tables.id"), index=True)
    match_id: Mapped[str] = mapped_column(String(64))
    requester_user_id: Mapped[str] = mapped_column(ForeignKey("nfc_users.id"), index=True)
    target_user_id: Mapped[str] = mapped_column(ForeignKey("nfc_users.id"), index=True)
    pair_key: Mapped[str] = mapped_column(String(64))
    requester_seat: Mapped[str] = mapped_column(String(5))
    target_seat: Mapped[str] = mapped_column(String(5))
    requester_membership_id: Mapped[str] = mapped_column(String(64))
    target_membership_id: Mapped[str] = mapped_column(String(64))
    requester_seat_version: Mapped[int] = mapped_column(Integer)
    target_seat_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    requested_at: Mapped[str] = mapped_column(String(40))
    expires_at: Mapped[str] = mapped_column(String(40), index=True)
    responded_at: Mapped[str | None] = mapped_column(String(40))
    responded_by: Mapped[str | None] = mapped_column(String(128))
    invalidated_reason: Mapped[str | None] = mapped_column(String(64))


class SeatSwapClaim(Base):
    """One user may participate in at most one pending request in either role."""
    __tablename__ = "seat_swap_claims"
    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("seat_swap_requests.id", ondelete="CASCADE"), index=True)
