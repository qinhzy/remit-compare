from remit_compare.core import BaseProvider, ProviderError, Quote, get_mid_rate

_PROVIDER_NAME = "Wise"

# Source: wise.com/gb/pricing/send-money — last verified 2026-04-18
# Variable fee applies to the full send_amount; fixed fee depends on send currency.
_VARIABLE_FEE_RATE = 0.0043  # 0.43%
_FIXED_FEE_BY_CURRENCY: dict[str, float] = {
    "GBP": 0.23,
    "USD": 1.00,
    "EUR": 0.29,
    "AUD": 0.45,
    "CAD": 0.50,
    "SGD": 0.60,
}
_FIXED_FEE_DEFAULT = 0.50
_ARRIVAL_HOURS = 24  # Wise typically 0–2 business days; use 24h as representative


def _wise_fee(send_amount: float, send_currency: str) -> float:
    fixed = _FIXED_FEE_BY_CURRENCY.get(send_currency.upper(), _FIXED_FEE_DEFAULT)
    return round(fixed + send_amount * _VARIABLE_FEE_RATE, 4)


class WiseProvider(BaseProvider):
    async def get_quote(
        self,
        send_amount: float,
        send_currency: str,
        receive_currency: str,
    ) -> Quote:
        if send_amount <= 0:
            raise ValueError(f"send_amount must be positive, got {send_amount}")

        try:
            mid_rate_d = await get_mid_rate(send_currency, receive_currency)
        except ProviderError as exc:
            raise ProviderError(_PROVIDER_NAME, str(exc)) from exc

        mid_rate = float(mid_rate_d)
        fee = _wise_fee(send_amount, send_currency)
        # Wise uses mid-market rate; fee is charged on top of send_amount
        receive_amount = round(send_amount * mid_rate, 2)
        total_cost = send_amount + fee
        markup = total_cost / (receive_amount / mid_rate) - 1  # ≈ fee / send_amount

        return Quote(
            provider_name=_PROVIDER_NAME,
            send_amount=send_amount,
            send_currency=send_currency.upper(),
            receive_amount=receive_amount,
            receive_currency=receive_currency.upper(),
            fee=fee,
            exchange_rate=mid_rate,
            exchange_rate_mid=mid_rate,
            total_cost_in_send_currency=total_cost,
            estimated_arrival_hours=_ARRIVAL_HOURS,
            markup_vs_mid_rate=round(markup, 6),
        )
