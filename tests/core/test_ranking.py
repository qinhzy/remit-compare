from remit_compare.core import Quote, RankingPreference, rank_quotes


def _quote(provider: str, markup: float, eta: int) -> Quote:
    return Quote(
        provider_name=provider,
        send_amount=100,
        send_currency="USD",
        receive_amount=700 - markup * 100,
        receive_currency="CNY",
        fee=1,
        exchange_rate=7,
        exchange_rate_mid=7.1,
        total_cost_in_send_currency=101,
        estimated_arrival_hours=eta,
        markup_vs_mid_rate=markup,
    )


def test_value_ranking_prefers_the_lowest_all_in_markup() -> None:
    ranked = rank_quotes(
        [_quote("Fast", 0.03, 1), _quote("Value", 0.01, 24)],
        RankingPreference.VALUE,
    )

    assert [item.quote.provider_name for item in ranked] == ["Value", "Fast"]
    assert [item.rank for item in ranked] == [1, 2]


def test_speed_ranking_prefers_the_shortest_arrival() -> None:
    ranked = rank_quotes(
        [_quote("Value", 0.01, 24), _quote("Fast", 0.03, 1)],
        RankingPreference.SPEED,
    )

    assert ranked[0].quote.provider_name == "Fast"


def test_balanced_ranking_uses_normalized_cost_and_time() -> None:
    ranked = rank_quotes(
        [
            _quote("Value", 0.01, 24),
            _quote("Middle", 0.02, 12),
            _quote("Fast", 0.03, 1),
        ],
        RankingPreference.BALANCED,
    )

    assert ranked[0].quote.provider_name == "Value"
    assert ranked[0].score < ranked[1].score < ranked[2].score


def test_empty_ranking_is_safe() -> None:
    assert rank_quotes([], RankingPreference.BALANCED) == []
