"""Test persistence and repositories."""

import json
from datetime import date
from pathlib import Path

import pytest

from vending.exceptions import InvalidSlotError
from vending.models import Coin, InventoryItem, Product, Transaction, TransactionOutcome
from vending.money import Money
from vending.persistence import (
    default_config_text,
    default_products_data,
    ensure_defaults,
    load_config,
    load_inventory,
    load_products,
    load_state,
    reset_factory,
    save_state_atomic,
    state_from_dict,
    state_to_dict,
)
from vending.repositories import (
    InMemoryInventoryRepository,
    InMemoryTransactionRepository,
    JsonInventoryRepository,
    JsonlTransactionRepository,
)
from vending.state import build_initial_state


def _sample_tx(outcome: TransactionOutcome = TransactionOutcome.COMPLETED) -> Transaction:
    return Transaction(
        started_at="2026-01-01T00:00:00+00:00",
        coins_inserted={Coin.DOLLAR: 2},
        slot_selected="A1",
        outcome=outcome,
        change_returned={Coin.QUARTER: 1},
        completed_at="2026-01-01T00:00:01+00:00",
        message="ok",
        paid=Money("2.00"),
        price=Money("1.75"),
        product_name="Bar",
    )


def test_default_resources_load() -> None:
    assert "service_pin_hash" in default_config_text()
    rows = default_products_data()
    assert isinstance(rows, list)
    assert rows


def test_load_config_ensure_defaults_and_reset_factory(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config = load_config(config_path)
    ensure_defaults(config)
    assert config.products_file.exists()
    assert config.inventory_file.exists()
    assert config.transactions_file.exists()

    reset_factory(config)
    assert config.products_file.exists()
    assert config.inventory_file.exists()
    assert config.transactions_file.exists()


def test_load_products_inventory_and_state_round_trip(tmp_path: Path) -> None:
    products_file = tmp_path / "products.json"
    products_file.write_text(
        json.dumps(
            [
                {
                    "slot": "A1",
                    "name": "Water",
                    "price": "1.25",
                    "category": "drink",
                    "quantity": 1,
                    "par_level": 2,
                }
            ]
        ),
        encoding="utf-8",
    )
    inventory_file = tmp_path / "inventory.json"
    inventory_file.write_text(
        json.dumps([{"slot": "A1", "quantity": 5, "par_level": 7}]),
        encoding="utf-8",
    )

    products = load_products(products_file)
    assert products["A1"].quantity == 1
    merged = load_inventory(products_file, inventory_file)
    assert merged["A1"].quantity == 5

    state = build_initial_state(merged, {Coin.QUARTER: 10})
    payload = state_to_dict(state)
    restored = state_from_dict(payload)
    assert restored.cash_total == state.cash_total
    assert restored.inventory["A1"].par_level == 7


def test_load_state_and_save_state_atomic(tmp_path: Path) -> None:
    config = load_config(tmp_path / "config.toml")
    state = load_state(config)
    out = tmp_path / "state.custom.json"
    save_state_atomic(state, out)
    loaded = load_state(config, out)
    assert loaded.inventory.keys() == state.inventory.keys()


def test_inmemory_inventory_repository_methods() -> None:
    inventory = {"A1": InventoryItem(Product("A1", "Water", Money("1.00")), 1, 2)}
    repo = InMemoryInventoryRepository(inventory)
    assert repo.load()["A1"].quantity == 1
    repo.adjust("A1", 3)
    assert repo.load()["A1"].quantity == 4
    repo.restock("A1", 1)
    assert repo.load()["A1"].quantity == 5
    repo.set_par("A1", 9)
    assert repo.load()["A1"].par_level == 9
    with pytest.raises(InvalidSlotError):
        repo.adjust("Z9", 1)


def test_json_inventory_repository_save_and_load(tmp_path: Path) -> None:
    products_file = tmp_path / "products.json"
    products_file.write_text(
        json.dumps(
            [{"slot": "A1", "name": "Water", "price": "1.00", "quantity": 0, "par_level": 2}]
        ),
        encoding="utf-8",
    )
    inv_file = tmp_path / "inventory.json"
    repo = JsonInventoryRepository(products_file, inv_file)
    base = repo.load()
    assert "A1" in base
    repo.save(base)
    assert inv_file.exists()


def test_transaction_repositories_query_and_aggregate(tmp_path: Path) -> None:
    tx_ok = _sample_tx()
    tx_fail = _sample_tx(TransactionOutcome.CANCELLED)

    mem = InMemoryTransactionRepository([tx_ok])
    mem.append(tx_fail)
    assert len(mem.query_by_date(date(2026, 1, 1))) == 2
    assert len(mem.query_by_slot("a1")) == 2
    agg = mem.aggregate()
    assert agg["count"] == 2
    assert agg["completed"] == 1

    path = tmp_path / "tx.jsonl"
    jsonl = JsonlTransactionRepository(path)
    jsonl.append(tx_ok)
    all_rows = jsonl.all()
    assert len(all_rows) == 1
