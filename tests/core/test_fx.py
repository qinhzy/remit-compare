import asyncio
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
    assert len(httpx_mock.get_requests()) == 1


async def test_concurrent_requests_share_one_upstream_call(
    httpx_mock: pytest_httpx.HTTPXMock,
):
    httpx_mock.add_response(method="GET", url=_FRANKFURTER_URL, json=_MOCK_RESPONSE)

    rates = await asyncio.gather(
        get_mid_rate("USD", "CNY"),
        get_mid_rate("usd", "cny"),
        get_mid_rate(" USD ", " CNY "),
    )

    assert rates == [Decimal("7.25")] * 3
    assert len(httpx_mock.get_requests()) == 1


async def test_inverse_pair_is_cached(httpx_mock: pytest_httpx.HTTPXMock):
    httpx_mock.add_response(method="GET", url=_FRANKFURTER_URL, json=_MOCK_RESPONSE)

    direct = await get_mid_rate("USD", "CNY")
    inverse = await get_mid_rate("CNY", "USD")

    assert inverse == Decimal("1") / direct
    assert len(httpx_mock.get_requests()) == 1


async def test_invalid_currency_is_rejected_before_http():
    with pytest.raises(ProviderError, match="Invalid ISO currency code"):
        await get_mid_rate("US", "CNY")


async def test_non_positive_rate_is_rejected(httpx_mock: pytest_httpx.HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url=_FRANKFURTER_URL,
        json={**_MOCK_RESPONSE, "rates": {"CNY": 0}},
    )

    with pytest.raises(ProviderError, match="rate must be positive"):
        await get_mid_rate("USD", "CNY")


async def test_malformed_decimal_rate_is_wrapped(httpx_mock: pytest_httpx.HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url=_FRANKFURTER_URL,
        json={**_MOCK_RESPONSE, "rates": {"CNY": "not-a-number"}},
    )

    with pytest.raises(ProviderError, match="Unexpected response format"):
        await get_mid_rate("USD", "CNY")


async def test_get_mid_rate_http_error_raises_provider_error(httpx_mock: pytest_httpx.HTTPXMock):
    """HTTP 500 from Frankfurter raises ProviderError."""
    httpx_mock.add_response(
        method="GET", url=_FRANKFURTER_URL, status_code=500, text="Server Error"
    )

    with pytest.raises(ProviderError, match=r"\[Frankfurter\].*500"):
        await get_mid_rate("USD", "CNY")
