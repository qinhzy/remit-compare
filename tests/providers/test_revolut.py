import pytest
import pytest_httpx

from remit_compare.core import ProviderError, Quote
from remit_compare.providers.revolut import _RATES_API_URL, RevolutProvider

_USD_RATES_URL = _RATES_API_URL.format(from_currency="USD", to_currency="CNY")

_MOCK_RATES_RESPONSE = {
    "amount": 1.0,
    "base": "USD",
    "date": "2026-04-17",
    "rates": {"CNY": 7.25},
}


@pytest.fixture
def provider():
    return RevolutProvider()


async def test_get_quote_success(httpx_mock: pytest_httpx.HTTPXMock, provider: RevolutProvider):
    """Normal USD→CNY quote returns correct Quote fields."""
    httpx_mock.add_response(method="GET", url=_USD_RATES_URL, json=_MOCK_RATES_RESPONSE)

    quote = await provider.get_quote(1000.0, "USD", "CNY")

    # effective_rate = 7.25 * (1 - 0.005) = 7.2138
    # receive_amount = (1000 - 0) * 7.2138 = 7213.75
    assert isinstance(quote, Quote)
    assert quote.provider_name == "Revolut"
    assert quote.send_amount == 1000.0
    assert quote.send_currency == "USD"
    assert quote.receive_currency == "CNY"
    assert quote.fee == pytest.approx(0.0)
    assert quote.exchange_rate == pytest.approx(7.25 * 0.995)
    assert quote.receive_amount == pytest.approx(1000.0 * 7.25 * 0.995, abs=0.01)
    assert quote.total_cost_in_send_currency == pytest.approx(1000.0)
    assert quote.estimated_arrival_hours == 48


async def test_zero_amount_raises_value_error(provider: RevolutProvider):
    """send_amount=0 raises ValueError before any HTTP call."""
    with pytest.raises(ValueError, match="send_amount must be positive"):
        await provider.get_quote(0, "USD", "CNY")


async def test_http_500_raises_provider_error(
    httpx_mock: pytest_httpx.HTTPXMock, provider: RevolutProvider
):
    """HTTP 500 from rate API raises ProviderError."""
    httpx_mock.add_response(
        method="GET", url=_USD_RATES_URL, status_code=500, text="Internal Server Error"
    )

    with pytest.raises(ProviderError, match=r"\[Revolut\].*500"):
        await provider.get_quote(100.0, "USD", "CNY")
