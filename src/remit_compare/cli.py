import asyncio

import typer

from remit_compare.core import ProviderError
from remit_compare.providers.wise import WiseProvider

app = typer.Typer(help="Compare cross-border remittance fees across providers.")

_PROVIDERS = [WiseProvider()]


async def _fetch_all(amount: float, from_currency: str, to_currency: str) -> list:
    results = []
    for p in _PROVIDERS:
        try:
            results.append(await p.get_quote(amount, from_currency, to_currency))
        except ProviderError as e:
            results.append(e)
    return results


@app.command()
def compare(
    amount: float = typer.Argument(..., help="Amount to send"),
    from_currency: str = typer.Option("USD", "--from", help="Send currency"),
    to_currency: str = typer.Option("CNY", "--to", help="Receive currency"),
) -> None:
    """Compare remittance quotes from all available providers."""
    typer.echo(f"Fetching quotes for {amount} {from_currency.upper()} → {to_currency.upper()}...\n")

    results = asyncio.run(_fetch_all(amount, from_currency, to_currency))

    fmt = "{:<12} {:>12} {:>8} {:>10} {:>12} {:>8}"
    typer.echo(fmt.format("Provider", "Receive", "Rate", "Fee", "Total Cost", "Arrival"))
    typer.echo("-" * 68)
    for r in results:
        if isinstance(r, ProviderError):
            typer.echo(f"  ERROR: {r}")
        else:
            typer.echo(fmt.format(
                r.provider_name,
                f"{r.receive_amount:.2f} {r.receive_currency}",
                f"{r.exchange_rate:.4f}",
                f"{r.fee:.2f} {r.send_currency}",
                f"{r.total_cost_in_send_currency:.2f} {r.send_currency}",
                f"~{r.estimated_arrival_hours}h",
            ))


@app.command()
def providers() -> None:
    """List all available remittance providers."""
    typer.echo("Available providers: Wise")


if __name__ == "__main__":
    app()
