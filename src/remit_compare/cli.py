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
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from remit_compare.core import (
    BaseProvider,
    ProviderError,
    Quote,
    RankedQuote,
    RankingPreference,
    rank_quotes,
)
from remit_compare.providers.paypal import PayPalProvider
from remit_compare.providers.revolut import RevolutProvider
from remit_compare.providers.wise import WiseProvider

app = typer.Typer(help="Compare cross-border remittance fees across providers.")
console = Console()

_PROVIDERS: list[BaseProvider] = [WiseProvider(), RevolutProvider(), PayPalProvider()]
_CURRENCY_CODE = re.compile(r"^[A-Z]{3}$")
_PROVIDER_TIMEOUT_SECONDS = 12.0


class OutputFormat(StrEnum):
    TABLE = "table"
    JSON = "json"
    CSV = "csv"


async def _fetch_all(
    amount: float,
    from_currency: str,
    to_currency: str,
    *,
    timeout_seconds: float = _PROVIDER_TIMEOUT_SECONDS,
    providers: list[BaseProvider] | None = None,
) -> list[Quote | ProviderError]:
    selected_providers = _PROVIDERS if providers is None else providers
    return await asyncio.gather(
        *[
            _fetch_provider(
                provider,
                amount,
                from_currency,
                to_currency,
                timeout_seconds=timeout_seconds,
            )
            for provider in selected_providers
        ]
    )


async def _fetch_provider(
    provider: BaseProvider,
    amount: float,
    from_currency: str,
    to_currency: str,
    *,
    timeout_seconds: float = _PROVIDER_TIMEOUT_SECONDS,
) -> Quote | ProviderError:
    try:
        quote = await asyncio.wait_for(
            provider.get_quote(amount, from_currency, to_currency),
            timeout=timeout_seconds,
        )
        return _validate_quote(
            quote,
            requested_amount=amount,
            requested_from_currency=from_currency,
            requested_to_currency=to_currency,
        )
    except TimeoutError:
        return ProviderError(
            _provider_name(provider),
            f"Quote timed out after {timeout_seconds:g} seconds",
        )
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
    prefer: RankingPreference = typer.Option(
        RankingPreference.VALUE,
        "--prefer",
        help="Recommendation preference: value, speed, or balanced",
        case_sensitive=False,
    ),
    timeout: float = typer.Option(
        _PROVIDER_TIMEOUT_SECONDS,
        "--timeout",
        help="Per-provider timeout in seconds (0.1 to 60)",
    ),
    provider: list[str] | None = typer.Option(
        None,
        "--provider",
        help="Only query this provider; repeat to select more than one",
    ),
) -> None:
    """Compare remittance quotes from all available providers."""
    if not math.isfinite(amount) or amount <= 0:
        raise typer.BadParameter("must be a positive finite number", param_hint="--amount")
    if not math.isfinite(timeout) or not 0.1 <= timeout <= 60:
        raise typer.BadParameter(
            "must be a finite number between 0.1 and 60",
            param_hint="--timeout",
        )

    src = _normalize_currency(from_currency, "--from")
    dst = _normalize_currency(to_currency, "--to")
    selected_providers = _select_providers(provider)
    if output_format is OutputFormat.TABLE:
        provider_names = ", ".join(_provider_name(item) for item in selected_providers)
        console.print(
            f"\nFetching quotes: [bold]{amount} {src} → {dst}[/bold]"
            f" · [dim]{provider_names}[/dim]\n"
        )

    if output_format is OutputFormat.TABLE and console.is_terminal:
        with console.status("Contacting providers…", spinner="dots"):
            results = asyncio.run(
                _fetch_all(
                    amount,
                    src,
                    dst,
                    timeout_seconds=timeout,
                    providers=selected_providers,
                )
            )
    else:
        results = asyncio.run(
            _fetch_all(
                amount,
                src,
                dst,
                timeout_seconds=timeout,
                providers=selected_providers,
            )
        )

    ranked_quotes = rank_quotes([r for r in results if isinstance(r, Quote)], prefer)
    errors = [r for r in results if isinstance(r, ProviderError)]

    if output_format is OutputFormat.JSON:
        _render_json(amount, src, dst, ranked_quotes, errors, prefer)
    elif output_format is OutputFormat.CSV:
        _render_csv(ranked_quotes, errors)
    else:
        _render_table(ranked_quotes, errors, prefer)

    if not ranked_quotes:
        raise typer.Exit(code=1)


def _render_table(
    ranked_quotes: list[RankedQuote],
    errors: list[ProviderError],
    preference: RankingPreference,
) -> None:
    table = Table(show_header=True, header_style="bold cyan", show_lines=False)
    table.add_column("Rank", justify="center", width=6)
    table.add_column("Provider", style="bold", min_width=10)
    table.add_column("Fee", justify="right", min_width=12)
    table.add_column("Exchange Rate", justify="right", min_width=14)
    table.add_column("You Receive", justify="right", min_width=16)
    table.add_column("Total Cost", justify="right", min_width=14)
    table.add_column("vs Mid-Rate", justify="right", min_width=12)
    table.add_column("ETA", justify="right", min_width=8)

    for ranked in ranked_quotes:
        q = ranked.quote
        markup_pct = f"{q.markup_vs_mid_rate * 100:.2f}%"
        table.add_row(
            "★" if ranked.rank == 1 else str(ranked.rank),
            Text(q.provider_name, style="bold green" if ranked.rank == 1 else None),
            f"{q.fee:.2f} {q.send_currency}",
            f"{q.exchange_rate:.4f}",
            f"{q.receive_amount:,.2f} {q.receive_currency}",
            f"{q.total_cost_in_send_currency:.2f} {q.send_currency}",
            markup_pct,
            f"~{q.estimated_arrival_hours}h",
        )

    for e in errors:
        table.add_row(
            "—",
            Text(e.provider, style="red"),
            Text(f"Error: {str(e)[:45]}", style="red"),
            "",
            "",
            "",
            "",
            "",
        )

    console.print(table)
    if ranked_quotes:
        _render_recommendation(ranked_quotes, preference)


def _render_json(
    amount: float,
    from_currency: str,
    to_currency: str,
    ranked_quotes: list[RankedQuote],
    errors: list[ProviderError],
    preference: RankingPreference,
) -> None:
    payload = {
        "query": {
            "amount": amount,
            "from_currency": from_currency,
            "to_currency": to_currency,
            "preference": preference.value,
        },
        "quotes": [
            {
                "rank": ranked.rank,
                "recommended": ranked.rank == 1,
                "score": round(ranked.score, 6),
                **asdict(ranked.quote),
            }
            for ranked in ranked_quotes
        ],
        "errors": [{"provider": error.provider, "message": error.message} for error in errors],
    }
    typer.echo(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    )


def _render_csv(ranked_quotes: list[RankedQuote], errors: list[ProviderError]) -> None:
    fieldnames = [
        "status",
        "rank",
        "recommended",
        "score",
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
    for ranked in ranked_quotes:
        writer.writerow(
            {
                "status": "ok",
                "rank": ranked.rank,
                "recommended": ranked.rank == 1,
                "score": round(ranked.score, 6),
                **asdict(ranked.quote),
                "error": "",
            }
        )
    for error in errors:
        writer.writerow(
            {
                "status": "error",
                "provider_name": error.provider,
                "error": error.message,
            }
        )
    typer.echo(output.getvalue(), nl=False)


def _render_recommendation(
    ranked_quotes: list[RankedQuote],
    preference: RankingPreference,
) -> None:
    best = ranked_quotes[0].quote
    reason = {
        RankingPreference.VALUE: "lowest all-in cost against the neutral mid-market rate",
        RankingPreference.SPEED: "shortest estimated arrival time",
        RankingPreference.BALANCED: "best normalized mix of all-in cost and arrival time",
    }[preference]
    summary = Text()
    summary.append(f"{best.provider_name}", style="bold green")
    summary.append(f" is recommended for {reason}.\n")
    summary.append("Recipient gets ", style="dim")
    summary.append(f"{best.receive_amount:,.2f} {best.receive_currency}", style="bold")
    summary.append(f" in about {best.estimated_arrival_hours}h", style="dim")
    if len(ranked_quotes) > 1:
        runner_up = ranked_quotes[1].quote
        receive_delta = best.receive_amount - runner_up.receive_amount
        eta_delta = best.estimated_arrival_hours - runner_up.estimated_arrival_hours
        summary.append("\nvs runner-up: ", style="dim")
        summary.append(f"{receive_delta:+,.2f} {best.receive_currency}")
        summary.append(f", {eta_delta:+d}h")
    console.print(
        Panel(
            summary,
            title=f"Recommendation · {preference.value}",
            border_style="green",
        )
    )


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


def _select_providers(requested: list[str] | None) -> list[BaseProvider]:
    if not requested:
        return _PROVIDERS

    available = {_provider_name(provider).casefold(): provider for provider in _PROVIDERS}
    selected: list[BaseProvider] = []
    seen: set[str] = set()
    for raw_name in requested:
        name = raw_name.strip().casefold()
        if name not in available:
            choices = ", ".join(_provider_name(provider) for provider in _PROVIDERS)
            raise typer.BadParameter(
                f"unknown provider {raw_name!r}; choose from {choices}",
                param_hint="--provider",
            )
        if name not in seen:
            selected.append(available[name])
            seen.add(name)
    return selected


def _validate_quote(
    quote: object,
    *,
    requested_amount: float,
    requested_from_currency: str,
    requested_to_currency: str,
) -> Quote:
    if not isinstance(quote, Quote):
        raise TypeError("provider must return a Quote")

    if not isinstance(quote.provider_name, str) or not quote.provider_name.strip():
        raise ValueError("provider returned an empty provider name")

    quote_from_currency = _normalize_quote_currency(quote.send_currency)
    quote_to_currency = _normalize_quote_currency(quote.receive_currency)
    if quote_from_currency != requested_from_currency or quote_to_currency != requested_to_currency:
        raise ValueError("provider returned a quote for the wrong currency pair")
    if not math.isclose(
        quote.send_amount,
        requested_amount,
        rel_tol=1e-12,
        abs_tol=1e-9,
    ):
        raise ValueError("provider returned a quote for the wrong send amount")

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
    if (
        not isinstance(quote.estimated_arrival_hours, int)
        or isinstance(quote.estimated_arrival_hours, bool)
        or quote.estimated_arrival_hours < 0
    ):
        raise ValueError("provider returned an invalid arrival estimate")
    return quote


def _normalize_quote_currency(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("provider returned a non-string currency code")
    normalized = value.strip().upper()
    if not _CURRENCY_CODE.fullmatch(normalized):
        raise ValueError("provider returned an invalid currency code")
    return normalized


if __name__ == "__main__":
    app()
