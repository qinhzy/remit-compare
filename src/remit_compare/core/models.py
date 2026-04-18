from dataclasses import dataclass


@dataclass
class Quote:
    provider_name: str
    send_amount: float
    send_currency: str
    receive_amount: float
    receive_currency: str
    fee: float
    exchange_rate: float
    total_cost_in_send_currency: float
    estimated_arrival_hours: int
