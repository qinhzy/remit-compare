import time
from decimal import Decimal

import httpx

from remit_compare.core.exceptions import ProviderError

# ECB official data via Frankfurter API — free, no auth, updates daily ~16:00 CET
# https://www.frankfurter.app/docs/
_FRANKFURTER_URL = "https://api.frankfurter.app/latest?from={from_currency}&to={to_currency}"
_CACHE_TTL_SECONDS = 300  # 5-minute TTL

_cache: dict[tuple[str, str], tuple[Decimal, float]] = {}


def _clear_cache() -> None:
    """Wipe the in-process rate cache. Intended for tests only."""
    _cache.clear()


async def get_mid_rate(
    from_currency: str,
    to_currency: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> Decimal:
    """Return the ECB mid-market exchange rate for the given currency pair.

    Results are cached for 5 minutes per process. Raises ProviderError on failure.
    """
    from_c = from_currency.upper()
    to_c = to_currency.upper()

    if from_c == to_c:
        return Decimal("1")

    key = (from_c, to_c)
    now = time.monotonic()
    cached = _cache.get(key)
    if cached and now - cached[1] < _CACHE_TTL_SECONDS:
        return cached[0]

    url = _FRANKFURTER_URL.format(from_currency=from_c, to_currency=to_c)
    owns_client = client is None
    _client = client or httpx.AsyncClient()
    try:
        response = await _client.get(url, follow_redirects=True)
    except httpx.RequestError as exc:
        raise ProviderError("Frankfurter", f"Network error: {exc}") from exc
    finally:
        if owns_client:
            await _client.aclose()

    if response.status_code != 200:
        raise ProviderError("Frankfurter", f"HTTP {response.status_code}: {response.text[:200]}")

    try:
        data = response.json()
        rate = Decimal(str(data["rates"][to_c]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ProviderError("Frankfurter", f"Unexpected response format: {exc}") from exc

    _cache[key] = (rate, now)
    return rate
