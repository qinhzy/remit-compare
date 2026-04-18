import httpx

from remit_compare.core import BaseProvider, ProviderError, Quote

_RATES_API_URL = "https://open.er-api.com/v6/latest/{currency}"
_PROVIDER_NAME = "PayPal"

# PayPal published fee structure (fee disclosure page, 2024)
_TRANSFER_FEE_RATE = 0.05    # 5% of send amount
_TRANSFER_FEE_MIN = 0.99     # USD minimum
_TRANSFER_FEE_MAX = 4.99     # USD maximum
_FX_SPREAD = 0.03            # ~3% currency conversion margin above mid-market


def _calc_transfer_fee(send_amount: float) -> float:
    return max(_TRANSFER_FEE_MIN, min(_TRANSFER_FEE_MAX, send_amount * _TRANSFER_FEE_RATE))


class PayPalProvider(BaseProvider):
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

        url = _RATES_API_URL.format(currency=send_currency.upper())
        client = self._client or httpx.AsyncClient()
        try:
            response = await client.get(url)
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
            if data.get("result") != "success":
                raise ValueError(f"API error: {data.get('error-type', 'unknown')}")
            mid_rate: float = float(data["rates"][receive_currency.upper()])
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError(_PROVIDER_NAME, f"Unexpected response format: {exc}") from exc

        effective_rate = mid_rate * (1 - _FX_SPREAD)
        fee = _calc_transfer_fee(send_amount)
        receive_amount = round(send_amount * effective_rate, 2)

        return Quote(
            provider_name=_PROVIDER_NAME,
            send_amount=send_amount,
            send_currency=send_currency.upper(),
            receive_amount=receive_amount,
            receive_currency=receive_currency.upper(),
            fee=fee,
            exchange_rate=effective_rate,
            total_cost_in_send_currency=send_amount + fee,
            estimated_arrival_hours=72,  # PayPal international: typically 3 business days
        )
