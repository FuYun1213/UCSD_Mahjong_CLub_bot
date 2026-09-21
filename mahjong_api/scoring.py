from decimal import Decimal

from .models import SEATS


def calculate_match_result(scores: dict[str, int], initial_points: int = 25000) -> dict:
    """原点结算：无 Oka，无额外顺位分（Uma）；此处可替换比赛规则。"""
    if set(scores) != set(SEATS):
        raise ValueError("需要东、南、西、北四个终局点数")
    if sum(scores.values()) != initial_points * 4:
        raise ValueError(f"终局总点数应为 {initial_points * 4}；请检查识别结果和未分配供托")
    return {
        seat: {
            "initial_points": initial_points,
            "final_points": scores[seat],
            "delta_points": scores[seat] - initial_points,
            "net_score": float(Decimal(scores[seat] - initial_points) / Decimal(1000)),
        }
        for seat in SEATS
    }
