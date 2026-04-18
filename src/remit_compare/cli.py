import typer

app = typer.Typer(help="Compare cross-border remittance fees across providers.")


@app.command()
def compare(
    amount: float = typer.Argument(..., help="Amount to send"),
    from_currency: str = typer.Option("USD", "--from", help="Send currency"),
    to_currency: str = typer.Option("CNY", "--to", help="Receive currency"),
) -> None:
    """Compare remittance quotes from all available providers."""
    typer.echo(f"Comparing {amount} {from_currency} → {to_currency} (providers coming soon)")


if __name__ == "__main__":
    app()
