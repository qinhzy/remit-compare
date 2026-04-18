from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from remit_compare.core import ProviderError, Quote
from remit_compare.providers.revolut import (
    _WEEKDAY_SPREAD,
    _WEEKEND_SPREAD,
    RevolutProvider,
    _fx_spread,
)

_MID_RATE = Decimal("7.25")
_PATCH = "remit_compare.providers.revolut.get_mid_rate"

_WEEKDAY = datetime(2026, 4, 20, 12, 0, tzinfo=UTC)  # Monday
_WEEKEND = datetime(2026, 4, 19, 12, 0, tzinfo=UTC)  # Sunday


@pytest.fixture
def weekday_provider():
    return RevolutProvider(_now=_WEEKDAY)


@pytest.fixture
def weekend_provider():
    return RevolutProvider(_now=_WEEKEND)


def test_fx_spread_weekday():
    assert _fx_spread(_WEEKDAY) == _WEEKDAY_SPREAD


def test_fx_spread_weekend():
    assert _fx_spread(_WEEKEND) == _WEEKEND_SPREAD


async def test_get_quote_weekday(weekday_provider: RevolutProvider):
    """Weekday: 0.5% spread applied, £0 fee, markup ~0.5%."""
    with patch(_PATCH, new_callable=AsyncMock, return_value=_MID_RATE):
        quote = await weekday_provider.get_quote(1000.0, "USD", "CNY")

    expected_rate = float(_MID_RATE) * 0.995
    assert isinstance(quote, Quote)
    assert quote.provider_name == "Revolut"
    assert quote.exchange_rate == pytest.approx(expected_rate)
    assert quote.exchange_rate_mid == pytest.approx(float(_MID_RATE))
    assert quote.fee == pytest.approx(0.0)
    assert quote.receive_amount == pytest.approx(1000.0 * expected_rate, abs=0.01)
    assert quote.total_cost_in_send_currency == pytest.approx(1000.0)
    assert quote.markup_vs_mid_rate == pytest.approx(0.005025, rel=1e-2)
    assert quote.estimated_arrival_hours == 48


async def test_get_quote_weekend(weekend_provider: RevolutProvider):
    """Weekend: 1% spread applied."""
    with patch(_PATCH, new_callable=AsyncMock, return_value=_MID_RATE):
        quote = await weekend_provider.get_quote(1000.0, "USD", "CNY")

    expected_rate = float(_MID_RATE) * 0.99
    assert quote.exchange_rate == pytest.approx(expected_rate)
    assert quote.markup_vs_mid_rate == pytest.approx(0.010101, rel=1e-2)


async def test_zero_amount_raises_value_error(weekday_provider: RevolutProvider):
    """send_amount=0 raises ValueError before calling get_mid_rate."""
    with pytest.raises(ValueError, match="send_amount must be positive"):
        await weekday_provider.get_quote(0, "USD", "CNY")


async def test_fx_error_wrapped_as_provider_error(weekday_provider: RevolutProvider):
    """ProviderError from get_mid_rate is re-raised under Revolut's name."""
    with patch(_PATCH, new_callable=AsyncMock, side_effect=ProviderError("Frankfurter", "timeout")):
        with pytest.raises(ProviderError, match=r"\[Revolut\]"):
            await weekday_provider.get_quote(100.0, "USD", "CNY")
