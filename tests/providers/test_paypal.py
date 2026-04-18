from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from remit_compare.core import ProviderError, Quote
from remit_compare.providers.paypal import PayPalProvider, _paypal_fee

_MID_RATE = Decimal("7.25")
_PATCH = "remit_compare.providers.paypal.get_mid_rate"


@pytest.fixture
def provider():
    return PayPalProvider()


async def test_get_quote_success(provider: PayPalProvider):
    """USD→CNY: 3.5% spread + 5% fee (capped at 4.99), markup ~8.7%."""
    with patch(_PATCH, new_callable=AsyncMock, return_value=_MID_RATE):
        quote = await provider.get_quote(1000.0, "USD", "CNY")

    # effective_rate = 7.25 * 0.965 = 6.99625
    # fee = min(max(50.0, 0.99), 4.99) = 4.99
    # receive = 1000 * 6.99625 = 6996.25
    # total_cost = 1004.99
    # markup = 1004.99 / (6996.25 / 7.25) - 1 = 1004.99 / 964.999 - 1 ≈ 4.14%
    assert isinstance(quote, Quote)
    assert quote.provider_name == "PayPal"
    assert quote.send_amount == 1000.0
    assert quote.send_currency == "USD"
    assert quote.receive_currency == "CNY"
    assert quote.exchange_rate == pytest.approx(7.25 * 0.965)
    assert quote.exchange_rate_mid == pytest.approx(7.25)
    assert quote.fee == pytest.approx(4.99)
    assert quote.receive_amount == pytest.approx(1000.0 * 7.25 * 0.965, abs=0.01)
    assert quote.total_cost_in_send_currency == pytest.approx(1004.99)
    assert quote.markup_vs_mid_rate == pytest.approx(1004.99 / 965.0 - 1, rel=1e-3)
    assert quote.estimated_arrival_hours == 72


async def test_zero_amount_raises_value_error(provider: PayPalProvider):
    """send_amount=0 raises ValueError before calling get_mid_rate."""
    with pytest.raises(ValueError, match="send_amount must be positive"):
        await provider.get_quote(0, "USD", "CNY")


async def test_fx_error_wrapped_as_provider_error(provider: PayPalProvider):
    """ProviderError from get_mid_rate is re-raised under PayPal's name."""
    with patch(_PATCH, new_callable=AsyncMock, side_effect=ProviderError("Frankfurter", "timeout")):
        with pytest.raises(ProviderError, match=r"\[PayPal\]"):
            await provider.get_quote(100.0, "USD", "CNY")


def test_paypal_fee_clamping():
    """Fee is capped at 4.99 and floored at 0.99."""
    assert _paypal_fee(1000.0) == pytest.approx(4.99)   # 5% = 50 → capped
    assert _paypal_fee(10.0) == pytest.approx(0.99)      # 5% = 0.50 → floored
    assert _paypal_fee(30.0) == pytest.approx(1.50)      # 5% = 1.50 → in range
