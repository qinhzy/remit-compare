import asyncio

import typer
from rich.console import Console
from rich.table import Table

from remit_compare.core import ProviderError, Quote
from remit_compare.providers.paypal import PayPalProvider
from remit_compare.providers.revolut import RevolutProvider
from remit_compare.providers.wise import WiseProvider

app = typer.Typer(help="Compare cross-border remittance fees across providers.")
console = Console()

_PROVIDERS = [WiseProvider(), RevolutProvider(), PayPalProvider()]


async def _fetch_all(
    amount: float, from_currency: str, to_currency: str
) -> list[Quote | ProviderError]:
    tasks = [p.get_quote(amount, from_currency, to_currency) for p in _PROVIDERS]
    raw = await asyncio.gather(*tasks, return_exceptions=True)
    return [
        r if isinstance(r, (Quote, ProviderError)) else ProviderError("unknown", str(r))
        for r in raw
    ]


@app.command()
def compare(
    amount: float = typer.Option(..., "--amount", help="Amount to send"),
    from_currency: str = typer.Option("USD", "--from", help="Send currency"),
    to_currency: str = typer.Option("CNY", "--to", help="Receive currency"),
) -> None:
    """Compare remittance quotes from all available providers."""
    src = from_currency.upper()
    dst = to_currency.upper()
    console.print(f"\nFetching quotes: [bold]{amount} {src} → {dst}[/bold]\n")

    results = asyncio.run(_fetch_all(amount, from_currency, to_currency))

    quotes = sorted(
        [r for r in results if isinstance(r, Quote)],
        key=lambda q: q.markup_vs_mid_rate,
    )
    errors = [r for r in results if isinstance(r, ProviderError)]

    table = Table(show_header=True, header_style="bold cyan", show_lines=False)
    table.add_column("Provider", style="bold", min_width=10)
    table.add_column("Fee", justify="right", min_width=12)
    table.add_column("Exchange Rate", justify="right", min_width=14)
    table.add_column("You Receive", justify="right", min_width=16)
    table.add_column("Total Cost", justify="right", min_width=14)
    table.add_column("vs Mid-Rate", justify="right", min_width=12)
    table.add_column("ETA", justify="right", min_width=8)

    for q in quotes:
        markup_pct = f"{q.markup_vs_mid_rate * 100:.2f}%"
        table.add_row(
            q.provider_name,
            f"{q.fee:.2f} {q.send_currency}",
            f"{q.exchange_rate:.4f}",
            f"{q.receive_amount:,.2f} {q.receive_currency}",
            f"{q.total_cost_in_send_currency:.2f} {q.send_currency}",
            markup_pct,
            f"~{q.estimated_arrival_hours}h",
        )

    for e in errors:
        table.add_row(
            f"[red]{e.provider}[/red]",
            f"[red]Error: {str(e)[:45]}[/red]",
            "", "", "", "", "",
        )

    console.print(table)


@app.command()
def providers() -> None:
    """List all available remittance providers."""
    for p in _PROVIDERS:
        console.print(f"  • {p.__class__.__name__}")


if __name__ == "__main__":
    app()
