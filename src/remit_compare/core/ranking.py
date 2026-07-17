from dataclasses import dataclass
from enum import StrEnum

from .models import Quote


class RankingPreference(StrEnum):
    VALUE = "value"
    SPEED = "speed"
    BALANCED = "balanced"


@dataclass(frozen=True, slots=True)
class RankedQuote:
    rank: int
    score: float
    quote: Quote


def rank_quotes(
    quotes: list[Quote],
    preference: RankingPreference = RankingPreference.VALUE,
) -> list[RankedQuote]:
    """Rank quotes with a deterministic, explainable cost/time score."""
    if not quotes:
        return []

    cost_values = [quote.markup_vs_mid_rate for quote in quotes]
    time_values = [float(quote.estimated_arrival_hours) for quote in quotes]
    scored: list[tuple[float, Quote]] = []

    for quote in quotes:
        cost_score = _normalize(quote.markup_vs_mid_rate, cost_values)
        time_score = _normalize(float(quote.estimated_arrival_hours), time_values)
        if preference is RankingPreference.SPEED:
            score = time_score
        elif preference is RankingPreference.BALANCED:
            score = 0.65 * cost_score + 0.35 * time_score
        else:
            score = cost_score
        scored.append((score, quote))

    scored.sort(
        key=lambda item: (
            item[0],
            item[1].markup_vs_mid_rate,
            item[1].estimated_arrival_hours,
            item[1].provider_name.casefold(),
        )
    )
    return [
        RankedQuote(rank=index, score=score, quote=quote)
        for index, (score, quote) in enumerate(scored, start=1)
    ]


def _normalize(value: float, values: list[float]) -> float:
    lower = min(values)
    upper = max(values)
    if upper == lower:
        return 0.0
    return (value - lower) / (upper - lower)
