from decimal import Decimal

import pytest
import pytest_httpx

from remit_compare.core.exceptions import ProviderError
from remit_compare.core.fx import _clear_cache, get_mid_rate

_FRANKFURTER_URL = "https://api.frankfurter.app/latest?from=USD&to=CNY"
_MOCK_RESPONSE = {"amount": 1.0, "base": "USD", "date": "2026-04-17", "rates": {"CNY": 7.25}}


@pytest.fixture(autouse=True)
def clear_rate_cache():
    """Ensure each test starts with a clean cache to prevent cross-test pollution."""
    _clear_cache()
    yield
    _clear_cache()


async def test_get_mid_rate_success(httpx_mock: pytest_httpx.HTTPXMock):
    """Returns a Decimal rate parsed from the Frankfurter response."""
    httpx_mock.add_response(method="GET", url=_FRANKFURTER_URL, json=_MOCK_RESPONSE)

    rate = await get_mid_rate("USD", "CNY")

    assert isinstance(rate, Decimal)
    assert rate == Decimal("7.25")


async def test_get_mid_rate_same_currency():
    """Same send/receive currency returns Decimal('1') without any HTTP call."""
    rate = await get_mid_rate("USD", "USD")
    assert rate == Decimal("1")


async def test_get_mid_rate_caches_result(httpx_mock: pytest_httpx.HTTPXMock):
    """Second call uses cache — only one HTTP request is made."""
    httpx_mock.add_response(method="GET", url=_FRANKFURTER_URL, json=_MOCK_RESPONSE)

    rate1 = await get_mid_rate("USD", "CNY")
    rate2 = await get_mid_rate("USD", "CNY")

    assert rate1 == rate2


async def test_get_mid_rate_http_error_raises_provider_error(httpx_mock: pytest_httpx.HTTPXMock):
    """HTTP 500 from Frankfurter raises ProviderError."""
    httpx_mock.add_response(
        method="GET", url=_FRANKFURTER_URL, status_code=500, text="Server Error"
    )

    with pytest.raises(ProviderError, match=r"\[Frankfurter\].*500"):
        await get_mid_rate("USD", "CNY")
