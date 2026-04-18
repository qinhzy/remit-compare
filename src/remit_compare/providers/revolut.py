from datetime import UTC, datetime
from decimal import Decimal

from remit_compare.core import BaseProvider, ProviderError, Quote, get_mid_rate

_PROVIDER_NAME = "Revolut"

# Source: revolut.com/en-GB/legal/fees — Standard personal plan, last verified 2026-04-18
# Weekday spread: 0.5% above mid-market rate (Mon–Fri)
# Weekend spread: 1.0% above mid-market rate (Sat–Sun)
# Transfer fee: £0 for most corridors on Standard plan
_WEEKDAY_SPREAD = Decimal("0.005")
_WEEKEND_SPREAD = Decimal("0.010")
_TRANSFER_FEE = 0.0
_ARRIVAL_HOURS = 48  # 1–3 business days; 48 h is typical


def _fx_spread(now: datetime) -> Decimal:
    """Return the applicable spread based on the day of the week (UTC)."""
    return _WEEKEND_SPREAD if now.weekday() >= 5 else _WEEKDAY_SPREAD


class RevolutProvider(BaseProvider):
    def __init__(self, *, _now: datetime | None = None) -> None:
        # _now is injected in tests to avoid weekday-flakiness
        self._now = _now

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

        now = self._now or datetime.now(UTC)
        spread = _fx_spread(now)
        effective_rate = float(mid_rate_d * (1 - spread))
        mid_rate = float(mid_rate_d)

        receive_amount = round(send_amount * effective_rate, 2)
        total_cost = send_amount + _TRANSFER_FEE
        markup = total_cost / (receive_amount / mid_rate) - 1

        return Quote(
            provider_name=_PROVIDER_NAME,
            send_amount=send_amount,
            send_currency=send_currency.upper(),
            receive_amount=receive_amount,
            receive_currency=receive_currency.upper(),
            fee=_TRANSFER_FEE,
            exchange_rate=effective_rate,
            exchange_rate_mid=mid_rate,
            total_cost_in_send_currency=total_cost,
            estimated_arrival_hours=_ARRIVAL_HOURS,
            markup_vs_mid_rate=round(markup, 6),
        )
