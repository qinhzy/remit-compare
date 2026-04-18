import httpx

from remit_compare.core import BaseProvider, ProviderError, Quote

# Frankfurter provides ECB/interbank rates; no auth required
_RATES_API_URL = "https://api.frankfurter.app/latest?from={from_currency}&to={to_currency}"
_PROVIDER_NAME = "Revolut"

# Revolut Standard plan (published fee schedule, 2024-2025)
#   - Exchange rate: interbank rate + ~0.5% spread on weekdays
#   - Transfer fee: £0 for most corridors on Standard plan
_FX_SPREAD = 0.005   # 0.5% above mid-market
_TRANSFER_FEE = 0.0  # Standard plan weekday domestic/SEPA; SWIFT may vary
_ARRIVAL_HOURS = 48  # Revolut international: 1-3 business days


class RevolutProvider(BaseProvider):
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client
        self._owns_client = client is None

    async def get_quote(
        self,
        send_amount: float,
        send_currency: str,
        receive_currency: str,
    ) -> Quote:
        if send_amount <= 0:
            raise ValueError(f"send_amount must be positive, got {send_amount}")

        url = _RATES_API_URL.format(
            from_currency=send_currency.upper(),
            to_currency=receive_currency.upper(),
        )
        client = self._client or httpx.AsyncClient()
        try:
            response = await client.get(url, follow_redirects=True)
        except httpx.RequestError as exc:
            raise ProviderError(_PROVIDER_NAME, f"Network error: {exc}") from exc
        finally:
            if self._owns_client and not self._client:
                await client.aclose()

        if response.status_code != 200:
            raise ProviderError(
                _PROVIDER_NAME,
                f"HTTP {response.status_code}: {response.text[:200]}",
            )

        try:
            data = response.json()
            mid_rate: float = float(data["rates"][receive_currency.upper()])
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError(_PROVIDER_NAME, f"Unexpected response format: {exc}") from exc

        # Revolut applies a small spread on top of mid-market
        effective_rate = mid_rate * (1 - _FX_SPREAD)
        receive_amount = round((send_amount - _TRANSFER_FEE) * effective_rate, 2)

        return Quote(
            provider_name=_PROVIDER_NAME,
            send_amount=send_amount,
            send_currency=send_currency.upper(),
            receive_amount=receive_amount,
            receive_currency=receive_currency.upper(),
            fee=_TRANSFER_FEE,
            exchange_rate=effective_rate,
            total_cost_in_send_currency=send_amount + _TRANSFER_FEE,
            estimated_arrival_hours=_ARRIVAL_HOURS,
        )
