"""The original Discord /record_game message, shared by every score entry."""


def _number(value, default=0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _rank(value):
    return int(_number(value, 999))


def _rank_change(before, after):
    change = before - after
    return f"🔺{change}" if change > 0 else f"🔻{abs(change)}" if change < 0 else "➖"


def build_game_summary(players, scores, final_time, pre_status, post_status,
                       yakuman_winner="", yakuman_deal_in="", yakuman_text=""):
    fields = []
    if yakuman_text:
        value = f"Winner: `{yakuman_winner}`"
        if yakuman_deal_in:
            value += f"\nDeal-in: `{yakuman_deal_in}`"
        value += f"\nYakuman: `{yakuman_text}`"
        fields.append({"name": "Yakuman", "value": value, "inline": False})
    for emoji, name, score in zip(["🐶", "🥈", "🥉", "🪦"], players, scores):
        pre, post = pre_status.get(name, {}), post_status.get(name, {})
        lines = []
        for metric, label in (("mmr", "MMR"), ("pt", "PT")):
            after = _number(post.get(metric))
            change = after - _number(pre.get(metric))
            before_rank, after_rank = _rank(pre.get(metric + "_rank")), _rank(post.get(metric + "_rank"))
            rank = after_rank if after_rank != 999 else "??"
            lines.append(f"**{label}**: `{after:.1f} ({change:+.1f})` | Rank #{rank} ({_rank_change(before_rank, after_rank)})")
        fields.append({"name": f"{emoji} {name} ({score})", "value": "\n".join(lines), "inline": False})
    return {"title": "✅ 结算完成 (Game Summary)", "description": f"**Time Recorded:** {final_time}",
            "color": 0x00FF00, "fields": fields}
