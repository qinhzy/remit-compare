import asyncio
import csv
import io
import json
import math
import re
from dataclasses import asdict
from enum import StrEnum

import typer
from rich.console import Console
from rich.table import Table

from remit_compare.core import BaseProvider, ProviderError, Quote
from remit_compare.providers.paypal import PayPalProvider
from remit_compare.providers.revolut import RevolutProvider
from remit_compare.providers.wise import WiseProvider

app = typer.Typer(help="Compare cross-border remittance fees across providers.")
console = Console()

_PROVIDERS: list[BaseProvider] = [WiseProvider(), RevolutProvider(), PayPalProvider()]
_CURRENCY_CODE = re.compile(r"^[A-Z]{3}$")


class OutputFormat(StrEnum):
    TABLE = "table"
    JSON = "json"
    CSV = "csv"


async def _fetch_all(
    amount: float, from_currency: str, to_currency: str
) -> list[Quote | ProviderError]:
    return await asyncio.gather(
        *[
            _fetch_provider(provider, amount, from_currency, to_currency)
            for provider in _PROVIDERS
        ]
    )


async def _fetch_provider(
    provider: BaseProvider,
    amount: float,
    from_currency: str,
    to_currency: str,
) -> Quote | ProviderError:
    try:
        quote = await provider.get_quote(amount, from_currency, to_currency)
        return _validate_quote(quote)
    except ProviderError as exc:
        return exc
    except Exception as exc:
        return ProviderError(_provider_name(provider), str(exc))


@app.command()
def compare(
    amount: float = typer.Option(..., "--amount", help="Amount to send"),
    from_currency: str = typer.Option("USD", "--from", help="Send currency"),
    to_currency: str = typer.Option("CNY", "--to", help="Receive currency"),
    output_format: OutputFormat = typer.Option(
        OutputFormat.TABLE,
        "--format",
        help="Output format: table, json, or csv",
        case_sensitive=False,
    ),
) -> None:
    """Compare remittance quotes from all available providers."""
    if not math.isfinite(amount) or amount <= 0:
        raise typer.BadParameter("must be a positive finite number", param_hint="--amount")

    src = _normalize_currency(from_currency, "--from")
    dst = _normalize_currency(to_currency, "--to")
    if output_format is OutputFormat.TABLE:
        console.print(f"\nFetching quotes: [bold]{amount} {src} → {dst}[/bold]\n")

    results = asyncio.run(_fetch_all(amount, src, dst))

    quotes = sorted(
        [r for r in results if isinstance(r, Quote)],
        key=lambda q: q.markup_vs_mid_rate,
    )
    errors = [r for r in results if isinstance(r, ProviderError)]

    if output_format is OutputFormat.JSON:
        _render_json(amount, src, dst, quotes, errors)
    elif output_format is OutputFormat.CSV:
        _render_csv(quotes, errors)
    else:
        _render_table(quotes, errors)

    if not quotes:
        raise typer.Exit(code=1)


def _render_table(quotes: list[Quote], errors: list[ProviderError]) -> None:
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


def _render_json(
    amount: float,
    from_currency: str,
    to_currency: str,
    quotes: list[Quote],
    errors: list[ProviderError],
) -> None:
    payload = {
        "query": {
            "amount": amount,
            "from_currency": from_currency,
            "to_currency": to_currency,
        },
        "quotes": [asdict(quote) for quote in quotes],
        "errors": [
            {"provider": error.provider, "message": error.message}
            for error in errors
        ],
    }
    typer.echo(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    )


def _render_csv(quotes: list[Quote], errors: list[ProviderError]) -> None:
    fieldnames = [
        "status",
        "provider_name",
        "send_amount",
        "send_currency",
        "receive_amount",
        "receive_currency",
        "fee",
        "exchange_rate",
        "exchange_rate_mid",
        "total_cost_in_send_currency",
        "estimated_arrival_hours",
        "markup_vs_mid_rate",
        "error",
    ]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for quote in quotes:
        writer.writerow({"status": "ok", **asdict(quote), "error": ""})
    for error in errors:
        writer.writerow(
            {
                "status": "error",
                "provider_name": error.provider,
                "error": error.message,
            }
        )
    typer.echo(output.getvalue(), nl=False)


@app.command()
def providers() -> None:
    """List all available remittance providers."""
    for p in _PROVIDERS:
        console.print(f"  • {_provider_name(p)}")


def _normalize_currency(value: str, param_hint: str) -> str:
    normalized = value.strip().upper()
    if not _CURRENCY_CODE.fullmatch(normalized):
        raise typer.BadParameter("must be a three-letter ISO currency code", param_hint=param_hint)
    return normalized


def _provider_name(provider: BaseProvider) -> str:
    return provider.__class__.__name__.removesuffix("Provider")


def _validate_quote(quote: object) -> Quote:
    if not isinstance(quote, Quote):
        raise TypeError("provider must return a Quote")

    positive_fields = (quote.send_amount, quote.exchange_rate, quote.exchange_rate_mid)
    non_negative_fields = (
        quote.receive_amount,
        quote.fee,
        quote.total_cost_in_send_currency,
    )
    if any(not math.isfinite(value) or value <= 0 for value in positive_fields):
        raise ValueError("provider returned an invalid positive quote value")
    if any(not math.isfinite(value) or value < 0 for value in non_negative_fields):
        raise ValueError("provider returned an invalid non-negative quote value")
    if not math.isfinite(quote.markup_vs_mid_rate):
        raise ValueError("provider returned a non-finite markup")
    if quote.estimated_arrival_hours < 0:
        raise ValueError("provider returned a negative arrival estimate")
    return quote


if __name__ == "__main__":
    app()
