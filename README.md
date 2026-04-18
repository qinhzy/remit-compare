# remit-compare

CLI tool to compare cross-border remittance fees across providers.

## Installation

```bash
uv sync --extra dev
```

## Usage

```bash
uv run remit-compare compare 1000 --from USD --to CNY
```

## Development

```bash
uv run pytest -x             # run tests
uv run ruff check src tests  # lint
uv run ruff format src tests # format
```
