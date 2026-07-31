import asyncio
import csv
import io
import json
from dataclasses import replace
from unittest.mock import AsyncMock, patch

from rich.console import Console
from typer.testing import CliRunner

from remit_compare.cli import (
    _fetch_provider,
    _format_runner_up_tradeoff,
    _render_table,
    app,
)
from remit_compare.core import (
    BaseProvider,
    ProviderError,
    Quote,
    RankingPreference,
    rank_quotes,
)

runner = CliRunner()


class InvalidQuoteProvider(BaseProvider):
    async def get_quote(
        self,
        send_amount: float,
        send_currency: str,
        receive_currency: str,
    ) -> Quote:
        quote = _quote()
        quote.receive_amount = float("inf")
        return quote


class SlowProvider(BaseProvider):
    async def get_quote(
        self,
        send_amount: float,
        send_currency: str,
        receive_currency: str,
    ) -> Quote:
        await asyncio.sleep(1)
        return _quote()


class WrongRequestProvider(BaseProvider):
    async def get_quote(
        self,
        send_amount: float,
        send_currency: str,
        receive_currency: str,
    ) -> Quote:
        quote = _quote()
        quote.send_amount = send_amount + 1
        quote.receive_currency = "EUR"
        return quote


def _quote() -> Quote:
    return Quote(
        provider_name="Wise",
        send_amount=100.0,
        send_currency="USD",
        receive_amount=725.0,
        receive_currency="CNY",
        fee=1.43,
        exchange_rate=7.25,
        exchange_rate_mid=7.25,
        total_cost_in_send_currency=101.43,
        estimated_arrival_hours=24,
        markup_vs_mid_rate=0.0143,
    )


def test_compare_json_is_machine_readable() -> None:
    results = [_quote(), ProviderError("PayPal", "temporarily unavailable")]
    with patch("remit_compare.cli._fetch_all", new=AsyncMock(return_value=results)):
        result = runner.invoke(
            app,
            ["compare", "--amount", "100", "--from", "usd", "--to", "cny", "--format", "json"],
        )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["query"]["from_currency"] == "USD"
    assert payload["query"]["preference"] == "value"
    assert payload["quotes"][0]["rank"] == 1
    assert payload["quotes"][0]["recommended"] is True
    assert payload["quotes"][0]["provider_name"] == "Wise"
    assert payload["errors"] == [{"provider": "PayPal", "message": "temporarily unavailable"}]


def test_compare_csv_has_success_and_error_rows() -> None:
    results = [_quote(), ProviderError("PayPal", "temporarily unavailable")]
    with patch("remit_compare.cli._fetch_all", new=AsyncMock(return_value=results)):
        result = runner.invoke(app, ["compare", "--amount", "100", "--format", "csv"])

    rows = list(csv.DictReader(io.StringIO(result.stdout)))
    assert result.exit_code == 0
    assert [row["status"] for row in rows] == ["ok", "error"]
    assert rows[1]["provider_name"] == "PayPal"


def test_compare_rejects_non_finite_amount() -> None:
    result = runner.invoke(app, ["compare", "--amount", "nan"])

    assert result.exit_code != 0
    assert "positive finite number" in result.output


def test_compare_rejects_non_finite_timeout() -> None:
    result = runner.invoke(app, ["compare", "--amount", "100", "--timeout", "nan"])

    assert result.exit_code != 0
    assert "finite number between 0.1 and 60" in result.output


def test_compare_forwards_custom_provider_timeout() -> None:
    fetch_all = AsyncMock(return_value=[_quote()])
    with patch("remit_compare.cli._fetch_all", new=fetch_all):
        result = runner.invoke(
            app,
            ["compare", "--amount", "100", "--timeout", "3.5", "--format", "json"],
        )

    assert result.exit_code == 0
    fetch_all.assert_awaited_once()
    assert fetch_all.await_args.args == (100.0, "USD", "CNY")
    assert fetch_all.await_args.kwargs["timeout_seconds"] == 3.5
    selected_names = [
        provider.__class__.__name__ for provider in fetch_all.await_args.kwargs["providers"]
    ]
    assert selected_names == [
        "WiseProvider",
        "RevolutProvider",
        "PayPalProvider",
    ]


def test_compare_can_limit_and_deduplicate_providers() -> None:
    fetch_all = AsyncMock(return_value=[_quote()])
    with patch("remit_compare.cli._fetch_all", new=fetch_all):
        result = runner.invoke(
            app,
            [
                "compare",
                "--amount",
                "100",
                "--provider",
                "wise",
                "--provider",
                "WISE",
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 0
    selected = fetch_all.await_args.kwargs["providers"]
    assert [provider.__class__.__name__ for provider in selected] == ["WiseProvider"]


def test_compare_rejects_unknown_provider_before_fetching() -> None:
    fetch_all = AsyncMock(return_value=[])
    with patch("remit_compare.cli._fetch_all", new=fetch_all):
        result = runner.invoke(
            app,
            ["compare", "--amount", "100", "--provider", "Unknown"],
        )

    assert result.exit_code != 0
    assert "unknown provider 'Unknown'" in result.output
    assert "Wise" in result.output
    assert "Revolut, PayPal" in result.output
    fetch_all.assert_not_awaited()


def test_compare_table_treats_provider_markup_as_plain_text() -> None:
    quote = replace(_quote(), provider_name="Wise [preview]")
    results = [quote, ProviderError("Pay[Pal]", "offline [retry]")]
    with patch("remit_compare.cli._fetch_all", new=AsyncMock(return_value=results)):
        result = runner.invoke(app, ["compare", "--amount", "100"])

    assert result.exit_code == 0
    assert "Wise [preview]" in result.output
    assert "Pay[Pal]" in result.output
    assert "offline" in result.output
    assert "[retry]" in result.output


def test_compare_table_separates_context_quotes_warnings_and_model_note() -> None:
    results = [_quote(), ProviderError("PayPal", "temporarily unavailable")]
    with patch("remit_compare.cli._fetch_all", new=AsyncMock(return_value=results)):
        result = runner.invoke(
            app,
            [
                "compare",
                "--amount",
                "100",
                "--prefer",
                "balanced",
                "--timeout",
                "3.5",
            ],
        )

    assert result.exit_code == 0
    assert "Comparison setup" in result.output
    assert "100.00 USD → CNY" in result.output
    assert "Balanced" in result.output
    assert "3.5s each" in result.output
    assert "Comparable quotes" in result.output
    assert "At a glance · balanced" in result.output
    assert "Provider warnings · 1" in result.output
    assert "Model note" in result.output
    assert "not a live retail quote" in result.output


def test_compare_table_adapts_to_narrow_and_wide_terminals() -> None:
    ranked = rank_quotes([_quote()], RankingPreference.VALUE)

    narrow_output = io.StringIO()
    narrow_console = Console(
        file=narrow_output,
        width=68,
        color_system=None,
        force_terminal=False,
    )
    with patch("remit_compare.cli.console", narrow_console):
        _render_table(ranked, [], RankingPreference.VALUE)

    narrow_text = narrow_output.getvalue()
    assert "You Receive" in narrow_text
    assert "All-in Cost" in narrow_text
    assert "Exchange Rate" not in narrow_text
    assert "Compact layout" in narrow_text

    wide_output = io.StringIO()
    wide_console = Console(
        file=wide_output,
        width=140,
        color_system=None,
        force_terminal=False,
    )
    with patch("remit_compare.cli.console", wide_console):
        _render_table(ranked, [], RankingPreference.VALUE)

    wide_text = wide_output.getvalue()
    assert "Exchange Rate" in wide_text
    assert "Compact layout" not in wide_text


def test_runner_up_tradeoff_uses_directional_plain_language() -> None:
    slower_value = replace(
        _quote(),
        provider_name="Value",
        receive_amount=730,
        estimated_arrival_hours=48,
    )
    faster_runner_up = replace(
        _quote(),
        provider_name="Fast",
        receive_amount=725,
        estimated_arrival_hours=24,
    )
    assert _format_runner_up_tradeoff(slower_value, faster_runner_up) == (
        "5.00 CNY more to recipient · 24h slower"
    )
    assert _format_runner_up_tradeoff(faster_runner_up, slower_value) == (
        "5.00 CNY less to recipient · 24h faster"
    )


def test_compare_returns_nonzero_when_every_provider_fails() -> None:
    with patch(
        "remit_compare.cli._fetch_all",
        new=AsyncMock(return_value=[ProviderError("Wise", "offline")]),
    ):
        result = runner.invoke(app, ["compare", "--amount", "100", "--format", "json"])

    assert result.exit_code == 1
    assert json.loads(result.stdout)["quotes"] == []


def test_compare_speed_preference_reorders_quotes() -> None:
    slow_value = replace(
        _quote(),
        provider_name="Value",
        estimated_arrival_hours=24,
        markup_vs_mid_rate=0.01,
    )
    fast = replace(
        _quote(),
        provider_name="Fast",
        estimated_arrival_hours=1,
        markup_vs_mid_rate=0.03,
    )
    with patch(
        "remit_compare.cli._fetch_all",
        new=AsyncMock(return_value=[slow_value, fast]),
    ):
        result = runner.invoke(
            app,
            ["compare", "--amount", "100", "--prefer", "speed", "--format", "json"],
        )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["query"]["preference"] == "speed"
    assert payload["quotes"][0]["provider_name"] == "Fast"


async def test_fetch_provider_rejects_non_finite_quotes() -> None:
    result = await _fetch_provider(InvalidQuoteProvider(), 100, "USD", "CNY")

    assert isinstance(result, ProviderError)
    assert result.provider == "InvalidQuote"
    assert "invalid non-negative quote value" in result.message


async def test_fetch_provider_times_out_without_blocking_other_quotes() -> None:
    result = await _fetch_provider(
        SlowProvider(),
        100,
        "USD",
        "CNY",
        timeout_seconds=0.001,
    )

    assert isinstance(result, ProviderError)
    assert result.provider == "Slow"
    assert "timed out" in result.message


async def test_fetch_provider_rejects_quote_for_a_different_request() -> None:
    result = await _fetch_provider(WrongRequestProvider(), 100, "USD", "CNY")

    assert isinstance(result, ProviderError)
    assert result.provider == "WrongRequest"
    assert "wrong currency pair" in result.message
