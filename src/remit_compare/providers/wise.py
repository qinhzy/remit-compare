from datetime import UTC, datetime

import httpx

from remit_compare.core import BaseProvider, ProviderError, Quote

_API_URL = "https://api.wise.com/v3/quotes"
_PROVIDER_NAME = "Wise"


def _arrival_hours(iso_timestamp: str) -> int:
    estimated = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
    delta = estimated - datetime.now(UTC)
    return max(1, int(delta.total_seconds() / 3600))


def _best_option(payment_options: list[dict]) -> dict:
    """Return the cheapest non-disabled BANK_TRANSFER payIn option."""
    candidates = [
        opt for opt in payment_options
        if not opt.get("disabled", False) and opt.get("payIn") == "BANK_TRANSFER"
    ]
    if not candidates:
        # Fall back to any non-disabled option
        candidates = [opt for opt in payment_options if not opt.get("disabled", False)]
    if not candidates:
        raise ValueError("No enabled payment options in response")
    return min(candidates, key=lambda o: o["fee"]["total"])


class WiseProvider(BaseProvider):
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

        payload = {
            "sourceCurrency": send_currency.upper(),
            "targetCurrency": receive_currency.upper(),
            "sourceAmount": send_amount,
        }

        client = self._client or httpx.AsyncClient()
        try:
            response = await client.post(_API_URL, json=payload)
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
            rate: float = float(data["rate"])
            opt = _best_option(data["paymentOptions"])
            fee: float = float(opt["fee"]["total"])
            receive_amount: float = float(opt["targetAmount"])
            arrival_hours = _arrival_hours(opt["estimatedDelivery"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError(_PROVIDER_NAME, f"Unexpected response format: {exc}") from exc

        return Quote(
            provider_name=_PROVIDER_NAME,
            send_amount=send_amount,
            send_currency=send_currency.upper(),
            receive_amount=receive_amount,
            receive_currency=receive_currency.upper(),
            fee=fee,
            exchange_rate=rate,
            total_cost_in_send_currency=send_amount + fee,
            estimated_arrival_hours=arrival_hours,
        )
