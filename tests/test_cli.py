import asyncio
import csv
import io
import json
from dataclasses import replace
from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from remit_compare.cli import _fetch_provider, app
from remit_compare.core import BaseProvider, ProviderError, Quote

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
    fetch_all.assert_awaited_once_with(
        100.0,
        "USD",
        "CNY",
        timeout_seconds=3.5,
    )


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
