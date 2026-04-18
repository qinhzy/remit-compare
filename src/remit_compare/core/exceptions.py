class ProviderError(Exception):
    """Raised when a provider fails to return a valid quote."""

    def __init__(self, provider: str, message: str) -> None:
        self.provider = provider
        super().__init__(f"[{provider}] {message}")
