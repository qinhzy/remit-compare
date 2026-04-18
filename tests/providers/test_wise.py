from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from remit_compare.core import ProviderError, Quote
from remit_compare.providers.wise import WiseProvider, _wise_fee

_MID_RATE = Decimal("9.25")
_PATCH = "remit_compare.providers.wise.get_mid_rate"


@pytest.fixture
def provider():
    return WiseProvider()


async def test_get_quote_success(provider: WiseProvider):
    """GBP→CNY: mid-rate used as exchange rate, fee = fixed + 0.43%."""
    with patch(_PATCH, new_callable=AsyncMock, return_value=_MID_RATE):
        quote = await provider.get_quote(1000.0, "GBP", "CNY")

    # fee = 0.23 + 1000 * 0.0043 = 4.53
    assert isinstance(quote, Quote)
    assert quote.provider_name == "Wise"
    assert quote.send_amount == 1000.0
    assert quote.send_currency == "GBP"
    assert quote.receive_currency == "CNY"
    assert quote.exchange_rate == pytest.approx(9.25)
    assert quote.exchange_rate_mid == pytest.approx(9.25)
    assert quote.fee == pytest.approx(4.53)
    assert quote.receive_amount == pytest.approx(1000.0 * 9.25, abs=0.01)
    assert quote.total_cost_in_send_currency == pytest.approx(1004.53)
    # markup ≈ fee / send_amount
    assert quote.markup_vs_mid_rate == pytest.approx(4.53 / 1000.0, rel=1e-3)
    assert quote.estimated_arrival_hours == 24


async def test_zero_amount_raises_value_error(provider: WiseProvider):
    """send_amount=0 raises ValueError before calling get_mid_rate."""
    with pytest.raises(ValueError, match="send_amount must be positive"):
        await provider.get_quote(0, "GBP", "CNY")


async def test_fx_error_wrapped_as_provider_error(provider: WiseProvider):
    """ProviderError from get_mid_rate is re-raised under Wise's name."""
    with patch(_PATCH, new_callable=AsyncMock, side_effect=ProviderError("Frankfurter", "timeout")):
        with pytest.raises(ProviderError, match=r"\[Wise\]"):
            await provider.get_quote(100.0, "USD", "CNY")


def test_wise_fee_fixed_component():
    """Fixed fee table: GBP uses £0.23, USD uses $1.00."""
    assert _wise_fee(1000.0, "GBP") == pytest.approx(0.23 + 4.30)
    assert _wise_fee(1000.0, "USD") == pytest.approx(1.00 + 4.30)
    assert _wise_fee(1000.0, "ZZZ") == pytest.approx(0.50 + 4.30)  # default
