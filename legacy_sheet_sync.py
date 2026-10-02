"""Write a complete legacy game and use Sheets' acknowledged position."""
from uuid import uuid4


def append_game(book, played_at, names, scores, deltas, afters, quarter,
                yakuman_winner="", yakuman_deal_in="", yakuman_text="", record_id=None):
    if len(deltas) != 4 or len(afters) != 4:
        raise ValueError("A game must be calculated before sheet publication")
    values = list(names) + list(scores) + list(deltas) + list(afters)
    values += ["✅ Calculated", quarter, yakuman_winner, yakuman_deal_in, yakuman_text]
    from mahjong_api.sheets import publish_marked_row
    from mahjong_api.history_delivery import digest
    marker = f"club-game-{record_id}" if record_id is not None else str(uuid4())
    row = publish_marked_row(book.worksheet("Games Riichi"), marker, values,
        marker_column=44, revision_column=45, payload_hash=digest(values))["row"]
    # The PT date is referenced by game-row number in the original workbook.
    # An independent append can select its metadata table and misalign the date.
    publish_marked_row(book.worksheet("Games/pt"), marker, [played_at], marker_column=28,
        revision_column=29, payload_hash=digest([played_at]), required_row=row)
    return row
