from tg_bot_aggregator.domain.ops.service import AUTO_APPLY_ACTIONS


def is_auto_apply_allowed(
    *,
    recommendation_type: str,
    recommendation_risk: str,
) -> bool:
    return recommendation_type in AUTO_APPLY_ACTIONS and recommendation_risk == "low"


__all__ = ["AUTO_APPLY_ACTIONS", "is_auto_apply_allowed"]
