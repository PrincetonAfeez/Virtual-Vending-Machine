# Virtual Vending Machine

A Python virtual vending machine built around immutable state transitions, exact `Decimal` money, bounded change-making, JSON persistence, reports, and repeatable customer simulation.

## Requirements

- **Python 3.11+** (see `requires-python` in `pyproject.toml`)
- **Runtime:** no third-party packages; the standard library and `decimal` are enough to run the app.
- **Development:** tests, coverage, lint, and type-checking use the optional **`dev`** extra (see `pyproject.toml`).

## Installation

From the project root:

```powershell
# Application only (editable install, no extra PyPI deps)
pip install -e .

# Application + dev tools (pytest, coverage, ruff, mypy, hypothesis)
pip install -e ".[dev]"
```

Alternatively, install dev dependencies via `requirements.txt` (editable install with `[dev]`):

```powershell
pip install -r requirements.txt
```

## Quick Start

```powershell
python -m vending run
```

On first run the app creates `~/.vending/config.toml`, `products.json`, `inventory.json`, `state.json`, and `transactions.jsonl`. The default service PIN is `1234`; change it by replacing `service_pin_hash` in the config with `vending.state.hash_pin("your-pin")`.

## Customer Commands

```text
insert quarter
q
select A1
A1
cancel
balance
service 1234
help
exit
```

## Operator Commands

```powershell
python -m vending admin
python -m vending report sales --by-day
python -m vending report inventory
python -m vending report cash --format json
python -m vending restock A1 10 --pin 1234
python -m vending simulate --customers 100 --seed 42
python -m vending audit
python -m vending reset --factory
```

Inside service mode:

```text
restock A1 20
restock-all
withdraw 20.00
set-price A1 1.75
add-product D1 "Protein Bar" 2.50 snack 8 4
remove-product D1
set-par A1 5
report inventory
audit-log
lock
unlock 1234
exit-service
```

## Project Layout

- `vending/money.py`: exact `Money` value object.
- `vending/models.py`: frozen products, inventory, state, transactions, modes, outcomes.
- `vending/state.py`: pure state transitions for customer and service workflows.
- `vending/change.py`: greedy and optimal bounded change algorithms.
- `vending/persistence.py`: config, catalog, state recovery, atomic saves.
- `vending/repositories.py`: JSON inventory and JSONL transaction repositories.
- `vending/renderers.py`: classic, compact, and minimal terminal renderers.
- `vending/reports.py`: sales, inventory, cash, top sellers, failed transactions, audit.
- `vending/simulation.py`: repeatable simulated customers.
- `vending/cli.py`: argparse entrypoints and interactive loop.
- `tests/`: pytest suite with coverage gate.

## Development

```powershell
# Tests (pytest is configured in pyproject.toml: coverage on `vending`, fail-under 95%)
pytest
# equivalent:
python -m pytest -q

python -m compileall vending
python -m ruff check .
python -m mypy vending
```

Coverage omits `vending/__main__.py` (thin `python -m vending` shim); all other `vending/` sources count toward the threshold. Configuration lives under `[tool.pytest.ini_options]`, `[tool.coverage.run]`, and `[tool.coverage.report]` in `pyproject.toml`.
