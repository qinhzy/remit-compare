import asyncio
import re
import time
from decimal import Decimal, DecimalException

import httpx

from remit_compare.core.exceptions import ProviderError

# ECB official data via Frankfurter API — free, no auth, updates daily ~16:00 CET
# https://www.frankfurter.app/docs/
_FRANKFURTER_URL = "https://api.frankfurter.app/latest?from={from_currency}&to={to_currency}"
_CACHE_TTL_SECONDS = 300  # 5-minute TTL
_REQUEST_TIMEOUT_SECONDS = 10.0
_CURRENCY_CODE = re.compile(r"^[A-Z]{3}$")

_cache: dict[tuple[str, str], tuple[Decimal, float]] = {}
_inflight: dict[tuple[str, str], asyncio.Task[Decimal]] = {}


def _clear_cache() -> None:
    """Wipe the in-process rate cache. Intended for tests only."""
    _cache.clear()
    for task in _inflight.values():
        if not task.done():
            task.cancel()
    _inflight.clear()


async def get_mid_rate(
    from_currency: str,
    to_currency: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> Decimal:
    """Return the ECB mid-market exchange rate for the given currency pair.

    Results are cached for 5 minutes per process. Raises ProviderError on failure.
    """
    from_c = _normalize_currency(from_currency)
    to_c = _normalize_currency(to_currency)

    if from_c == to_c:
        return Decimal("1")

    key = (from_c, to_c)
    now = time.monotonic()
    cached = _cache.get(key)
    if cached and now - cached[1] < _CACHE_TTL_SECONDS:
        return cached[0]

    current_task = _inflight.get(key)
    if current_task is not None and current_task.get_loop() is asyncio.get_running_loop():
        return await asyncio.shield(current_task)

    task = asyncio.create_task(_fetch_mid_rate(from_c, to_c, client=client))
    _inflight[key] = task

    def remove_completed(completed: asyncio.Task[Decimal]) -> None:
        if _inflight.get(key) is completed:
            _inflight.pop(key, None)

    task.add_done_callback(remove_completed)
    return await asyncio.shield(task)


async def _fetch_mid_rate(
    from_currency: str,
    to_currency: str,
    *,
    client: httpx.AsyncClient | None,
) -> Decimal:
    key = (from_currency, to_currency)
    now = time.monotonic()
    cached = _cache.get(key)
    if cached and now - cached[1] < _CACHE_TTL_SECONDS:
        return cached[0]

    url = _FRANKFURTER_URL.format(
        from_currency=from_currency,
        to_currency=to_currency,
    )
    owns_client = client is None
    _client = client or httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS)
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
        rate = Decimal(str(data["rates"][to_currency]))
    except (DecimalException, KeyError, TypeError, ValueError) as exc:
        raise ProviderError("Frankfurter", f"Unexpected response format: {exc}") from exc

    if not rate.is_finite() or rate <= 0:
        raise ProviderError("Frankfurter", "Unexpected response format: rate must be positive")

    cached_at = time.monotonic()
    _cache[key] = (rate, cached_at)
    _cache[(to_currency, from_currency)] = (Decimal("1") / rate, cached_at)
    return rate


def _normalize_currency(currency: str) -> str:
    normalized = currency.strip().upper()
    if not _CURRENCY_CODE.fullmatch(normalized):
        raise ProviderError("Frankfurter", f"Invalid ISO currency code: {currency!r}")
    return normalized
