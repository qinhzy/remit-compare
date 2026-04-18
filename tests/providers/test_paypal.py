import pytest
import pytest_httpx

from remit_compare.core import ProviderError, Quote
from remit_compare.providers.paypal import _RATES_API_URL, PayPalProvider

_USD_RATES_URL = _RATES_API_URL.format(currency="USD")

_MOCK_RATES_RESPONSE = {
    "result": "success",
    "base_code": "USD",
    "rates": {"CNY": 7.25, "USD": 1.0},
}


@pytest.fixture
def provider():
    return PayPalProvider()


async def test_get_quote_success(httpx_mock: pytest_httpx.HTTPXMock, provider: PayPalProvider):
    """Normal USD→CNY quote returns correct Quote fields."""
    httpx_mock.add_response(method="GET", url=_USD_RATES_URL, json=_MOCK_RATES_RESPONSE)

    quote = await provider.get_quote(1000.0, "USD", "CNY")

    # fee = min(max(1000 * 0.05, 0.99), 4.99) = 4.99
    # effective_rate = 7.25 * 0.97 = 7.0325
    assert isinstance(quote, Quote)
    assert quote.provider_name == "PayPal"
    assert quote.send_amount == 1000.0
    assert quote.send_currency == "USD"
    assert quote.receive_currency == "CNY"
    assert quote.fee == pytest.approx(4.99)
    assert quote.exchange_rate == pytest.approx(7.25 * 0.97)
    assert quote.receive_amount == pytest.approx(1000.0 * 7.25 * 0.97, abs=0.01)
    assert quote.total_cost_in_send_currency == pytest.approx(1004.99)
    assert quote.estimated_arrival_hours == 72


async def test_zero_amount_raises_value_error(provider: PayPalProvider):
    """send_amount=0 raises ValueError before any HTTP call."""
    with pytest.raises(ValueError, match="send_amount must be positive"):
        await provider.get_quote(0, "USD", "CNY")


async def test_http_500_raises_provider_error(
    httpx_mock: pytest_httpx.HTTPXMock, provider: PayPalProvider
):
    """HTTP 500 from rate API raises ProviderError."""
    httpx_mock.add_response(
        method="GET", url=_USD_RATES_URL, status_code=500, text="Internal Server Error"
    )

    with pytest.raises(ProviderError, match=r"\[PayPal\].*500"):
        await provider.get_quote(100.0, "USD", "CNY")
