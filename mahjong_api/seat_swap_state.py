"""Small transaction-local state transitions shared by all membership writers."""
from sqlalchemy import delete, or_, select
from .seat_swap_models import SeatSwapRequest, SeatSwapClaim
from .external_sync import audit
from .store import now


def finish_swap(db, request, status, actor="system", reason=None, timestamp=None):
    if request.status != "pending":
        return False
    request.status = status
    request.responded_at = timestamp or now()
    request.responded_by = str(actor)
    request.invalidated_reason = reason
    db.execute(delete(SeatSwapClaim).where(SeatSwapClaim.request_id == request.id))
    audit(db, "", actor, "seat_swap_" + status, {"request_id":request.id, "table_id":request.table_id,
        "requester_user_id":request.requester_user_id, "target_user_id":request.target_user_id,
        "requester_old_seat":request.requester_seat, "target_old_seat":request.target_seat,
        "requester_new_seat":request.target_seat if status == "accepted" else request.requester_seat,
        "target_new_seat":request.requester_seat if status == "accepted" else request.target_seat,
        "requested_at":request.requested_at, "responded_at":request.responded_at,
        "accepted_at":request.responded_at if status == "accepted" else None,
        "status":status, "reason":reason})
    return True


def invalidate_swaps(db, table_id, *, user_ids=None, reason="membership_changed", actor="system", timestamp=None):
    query = select(SeatSwapRequest).where(SeatSwapRequest.table_id == table_id, SeatSwapRequest.status == "pending")
    if user_ids is not None:
        users = [str(user_id) for user_id in user_ids]
        query = query.where(or_(SeatSwapRequest.requester_user_id.in_(users), SeatSwapRequest.target_user_id.in_(users)))
    for request in db.scalars(query):
        finish_swap(db, request, "invalidated", actor, reason, timestamp)
