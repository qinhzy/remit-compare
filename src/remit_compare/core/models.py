from dataclasses import dataclass


@dataclass
class Quote:
    provider_name: str
    send_amount: float
    send_currency: str
    receive_amount: float
    receive_currency: str
    fee: float
    exchange_rate: float           # effective rate after provider's spread
    exchange_rate_mid: float       # ECB mid-market rate (Frankfurter)
    total_cost_in_send_currency: float
    estimated_arrival_hours: int
    markup_vs_mid_rate: float      # fraction, e.g. 0.035 = 3.5% above mid-market cost
