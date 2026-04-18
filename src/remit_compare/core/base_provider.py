from abc import ABC, abstractmethod

from .models import Quote


class BaseProvider(ABC):
    @abstractmethod
    async def get_quote(
        self,
        send_amount: float,
        send_currency: str,
        receive_currency: str,
    ) -> Quote:
        """Fetch a remittance quote for the given amount and currency pair."""
        ...
