import pytest
import pytest_httpx

from remit_compare.core import ProviderError, Quote
from remit_compare.providers.wise import _API_URL, WiseProvider

# A realistic Wise API response with two payment options (bank transfer cheapest)
_MOCK_RESPONSE = {
    "sourceCurrency": "GBP",
    "targetCurrency": "CNY",
    "rate": 9.25,
    "status": "PENDING",
    "paymentOptions": [
        {
            "payIn": "BANK_TRANSFER",
            "payOut": "BANK_TRANSFER",
            "disabled": False,
            "sourceAmount": 500.0,
            "targetAmount": 4593.75,
            "estimatedDelivery": "2099-01-01T12:00:00Z",
            "fee": {
                "transferwise": 11.0, "payIn": 3.5, "discount": 0, "total": 14.5, "partner": 0.0
            },
        },
        {
            "payIn": "DEBIT",
            "payOut": "BANK_TRANSFER",
            "disabled": False,
            "sourceAmount": 500.0,
            "targetAmount": 4560.0,
            "estimatedDelivery": "2099-01-01T12:00:00Z",
            "fee": {
                "transferwise": 11.0, "payIn": 20.0, "discount": 0, "total": 31.0, "partner": 0.0
            },
        },
    ],
}


@pytest.fixture
def provider():
    return WiseProvider()


async def test_get_quote_success(httpx_mock: pytest_httpx.HTTPXMock, provider: WiseProvider):
    """Normal GBP→CNY quote picks the cheapest BANK_TRANSFER option."""
    httpx_mock.add_response(method="POST", url=_API_URL, json=_MOCK_RESPONSE, status_code=200)

    quote = await provider.get_quote(500.0, "GBP", "CNY")

    assert isinstance(quote, Quote)
    assert quote.provider_name == "Wise"
    assert quote.send_amount == 500.0
    assert quote.send_currency == "GBP"
    assert quote.receive_amount == 4593.75
    assert quote.receive_currency == "CNY"
    assert quote.fee == pytest.approx(14.5)
    assert quote.exchange_rate == pytest.approx(9.25)
    assert quote.total_cost_in_send_currency == pytest.approx(514.5)
    assert quote.estimated_arrival_hours >= 1


async def test_zero_amount_raises_value_error(provider: WiseProvider):
    """send_amount=0 raises ValueError before any HTTP call."""
    with pytest.raises(ValueError, match="send_amount must be positive"):
        await provider.get_quote(0, "GBP", "CNY")


async def test_http_500_raises_provider_error(
    httpx_mock: pytest_httpx.HTTPXMock, provider: WiseProvider
):
    """HTTP 500 from Wise API raises ProviderError."""
    httpx_mock.add_response(
        method="POST", url=_API_URL, status_code=500, text="Internal Server Error"
    )

    with pytest.raises(ProviderError, match=r"\[Wise\].*500"):
        await provider.get_quote(100.0, "USD", "CNY")
