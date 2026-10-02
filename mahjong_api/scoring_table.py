"""Read-only scoring-table policy shared by every ordinary scoring entry."""
from .store import Conflict


def table_order(table):
    try:
        number = int(table.get("number"))
    except (ValueError, TypeError):
        number = float("inf")
    return number, str(table["id"])


def active_table(table):
    return (table.get("status") == "open" and not table.get("deleted_at")
            and not table.get("tournament_id") and bool(table.get("score_table_id")))


def resolve_scoring_table(available_tables, user_id, *, requested_table=None, current_table=None,
                          auto_select_full=False):
    """Explicit context > pinned view > membership > first joinable table.

    Pinning applies only while a page is open. A full table remains visible;
    closing/deleting it invalidates the pin. This function never creates seats.
    Ordinary entry may skip a full requested table when the viewer is not a
    member. Explicit manual selection and token-bound entry keep their table.
    The caller must validate entry tokens before passing their bound table ID.
    """
    tables = sorted(available_tables, key=table_order)
    def find(key):
        return next((t for t in tables if key in (t["id"], t.get("score_table_id"))), None)
    def belongs(table):
        return any(str(m["user_id"]) == str(user_id)
                   and m.get("status", "active") == "active" and not m.get("left_at")
                   for m in table.get("members", []))

    if requested_table is not None:
        table = find(requested_table)
        if table is None:
            raise Conflict("table_not_found", "table_not_found")
        if not active_table(table):
            raise Conflict("table_closed", "table_closed")
        if auto_select_full and table["player_count"] >= table["capacity"] and not belongs(table):
            # Ordinary entry links can carry the previous default table.
            # Choose the viewer's own table or the next joinable table once,
            # without changing any membership or assigning a wind.
            result = resolve_scoring_table(tables, user_id)
            result["notice"] = "full_table_redirected" if result["table"] else "full_table_no_space"
            return result
        return {"table": table, "source": "requested", "notice": None}

    notice = None
    if current_table:
        table = find(current_table)
        if table and active_table(table):
            return {"table": table, "source": "current_view", "notice": None}
        notice = "table_closed" if table else "table_not_found"

    for table in tables:
        if active_table(table) and belongs(table):
            return {"table": table, "source": "membership", "notice": notice}
    table = next((t for t in tables if active_table(t) and t.get("can_join")
                  and t["player_count"] < t["capacity"]), None)
    return {"table": table, "source": "available" if table else "empty", "notice": notice}
