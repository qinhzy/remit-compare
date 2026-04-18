import pytest
import pytest_httpx

from remit_compare.core import ProviderError, Quote
from remit_compare.providers.revolut import _API_URL, RevolutProvider

_MOCK_RESPONSE = {
    "fromCurrency": "USD",
    "toCurrency": "CNY",
    "rate": 7.25,
    "fee": 150,        # 1.50 USD in minor units
    "toAmount": 724625,  # 7246.25 CNY in minor units
    "estimatedDeliveryHours": 24,
}


@pytest.fixture
def provider():
    return RevolutProvider()


async def test_get_quote_success(httpx_mock: pytest_httpx.HTTPXMock, provider: RevolutProvider):
    """Normal USD→CNY quote returns correct Quote fields."""
    httpx_mock.add_response(method="POST", url=_API_URL, json=_MOCK_RESPONSE, status_code=200)

    quote = await provider.get_quote(1000.0, "USD", "CNY")

    assert isinstance(quote, Quote)
    assert quote.provider_name == "Revolut"
    assert quote.send_amount == 1000.0
    assert quote.send_currency == "USD"
    assert quote.receive_amount == pytest.approx(7246.25)
    assert quote.receive_currency == "CNY"
    assert quote.fee == pytest.approx(1.50)
    assert quote.exchange_rate == pytest.approx(7.25)
    assert quote.total_cost_in_send_currency == pytest.approx(1001.50)
    assert quote.estimated_arrival_hours == 24


async def test_zero_amount_raises_value_error(provider: RevolutProvider):
    """send_amount=0 raises ValueError before any HTTP call."""
    with pytest.raises(ValueError, match="send_amount must be positive"):
        await provider.get_quote(0, "USD", "CNY")


async def test_http_500_raises_provider_error(
    httpx_mock: pytest_httpx.HTTPXMock, provider: RevolutProvider
):
    """HTTP 500 from Revolut API raises ProviderError."""
    httpx_mock.add_response(
        method="POST", url=_API_URL, status_code=500, text="Internal Server Error"
    )

    with pytest.raises(ProviderError, match=r"\[Revolut\].*500"):
        await provider.get_quote(100.0, "USD", "CNY")
