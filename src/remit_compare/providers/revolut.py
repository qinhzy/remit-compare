import httpx

from remit_compare.core import BaseProvider, ProviderError, Quote

_API_URL = "https://www.revolut.com/api/quote/v2/transfer"
_PROVIDER_NAME = "Revolut"


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

        payload = {
            "fromCurrency": send_currency.upper(),
            "toCurrency": receive_currency.upper(),
            "fromAmount": int(send_amount * 100),  # Revolut uses minor units
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
            fee: float = float(data["fee"]) / 100  # minor units → major
            receive_amount: float = float(data["toAmount"]) / 100
            arrival_hours: int = int(data.get("estimatedDeliveryHours", 24))
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
