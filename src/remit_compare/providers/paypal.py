from decimal import Decimal

from remit_compare.core import BaseProvider, ProviderError, Quote, get_mid_rate

_PROVIDER_NAME = "PayPal"

# Source: paypal.com/us/webapps/mpp/paypal-fees — last verified 2026-04-18
# Currency conversion margin: 3.5% below mid-market rate (disclosed range: 3–4%)
# Transfer fee: 5% of send amount, min $0.99 USD-equivalent, max $4.99 USD-equivalent
_FX_SPREAD = Decimal("0.035")        # 3.5% conversion margin
_TRANSFER_FEE_RATE = Decimal("0.05") # 5%
_TRANSFER_FEE_MIN = 0.99
_TRANSFER_FEE_MAX = 4.99
_ARRIVAL_HOURS = 72  # PayPal international transfers: typically 3 business days


def _paypal_fee(send_amount: float) -> float:
    return max(_TRANSFER_FEE_MIN, min(_TRANSFER_FEE_MAX, send_amount * float(_TRANSFER_FEE_RATE)))


class PayPalProvider(BaseProvider):
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
        effective_rate = float(mid_rate_d * (1 - _FX_SPREAD))
        fee = _paypal_fee(send_amount)

        receive_amount = round(send_amount * effective_rate, 2)
        total_cost = send_amount + fee
        markup = total_cost / (receive_amount / mid_rate) - 1

        return Quote(
            provider_name=_PROVIDER_NAME,
            send_amount=send_amount,
            send_currency=send_currency.upper(),
            receive_amount=receive_amount,
            receive_currency=receive_currency.upper(),
            fee=fee,
            exchange_rate=effective_rate,
            exchange_rate_mid=mid_rate,
            total_cost_in_send_currency=total_cost,
            estimated_arrival_hours=_ARRIVAL_HOURS,
            markup_vs_mid_rate=round(markup, 6),
        )
