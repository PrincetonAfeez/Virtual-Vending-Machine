"""Test state, CLI, and extra functionality."""

from argparse import Namespace
from pathlib import Path

import pytest

from vending.change import get_change_algorithm
from vending.cli import build_parser, command_help, make_report, receipt
from vending.exceptions import AccessDeniedError, InvalidCoinError, InvalidSlotError
from vending.models import Coin, InventoryItem, Mode, Product, TransactionOutcome, TransactionResult
from vending.money import Money
from vending.persistence import load_config
from vending.repositories import InMemoryTransactionRepository
from vending.state import (
    add_product,
    build_initial_state,
    cancel_transaction,
    enter_service_mode,
    exact_change_required,
    exit_service_mode,
    format_change,
    hash_pin,
    insert_coin,
    lock_machine,
    normalize_slot,
    remove_product,
    restock_all_to_par,
    restock_slot,
    set_par_level,
    set_price,
    unlock_machine,
    validate_slot_code,
    withdraw_cash,
)


def _state():
    item = InventoryItem(Product("A1", "Water", Money("1.25"), "drink"), quantity=1, par_level=3)
    return build_initial_state({"a1": item}, {Coin.QUARTER: 10, Coin.DOLLAR: 1})


def test_state_slot_and_pin_helpers() -> None:
    assert len(hash_pin("1234")) == 64
    assert normalize_slot(" a1 ") == "A1"
    assert validate_slot_code("b2") == "B2"
    with pytest.raises(InvalidSlotError):
        validate_slot_code("99")


def test_state_service_operations_and_customer_paths() -> None:
    state = _state()
    with pytest.raises(InvalidCoinError):
        insert_coin(state, "bad-coin")

    state = insert_coin(state, Coin.DOLLAR)
    state, insufficient = cancel_transaction(state)
    assert insufficient.outcome == TransactionOutcome.CANCELLED

    state = enter_service_mode(state, "1234", hash_pin("1234"))
    state = restock_slot(state, "A1", 2)
    state = set_par_level(state, "A1", 5)
    state = set_price(state, "A1", Money("1.50"))
    state = add_product(state, "B1", "Chips", Money("2.00"), "snack", 4, 2)
    state = remove_product(state, "B1")
    state = restock_all_to_par(state)
    state = lock_machine(state)
    assert state.mode == Mode.LOCKED
    state = unlock_machine(state, "1234", hash_pin("1234"))
    state, withdrawn = withdraw_cash(enter_service_mode(state, "1234", hash_pin("1234")))
    assert isinstance(withdrawn, dict)
    state = exit_service_mode(state)
    assert state.mode == Mode.NORMAL


def test_state_access_control_and_format_helpers() -> None:
    state = _state()
    with pytest.raises(AccessDeniedError):
        unlock_machine(state, "1111", hash_pin("1234"))
    assert exact_change_required(Money("0.30"), {Coin.QUARTER: 1}) is True
    assert format_change({}) == "$0.00"
    assert "quarter" in format_change({Coin.QUARTER: 2})


def test_cli_build_parser_and_text_helpers(tmp_path: Path) -> None:
    parser = build_parser()
    args = parser.parse_args(["simulate", "--customers", "3"])
    assert args.command == "simulate"
    assert "Service:" in command_help(service=True)

    complete_receipt = receipt(
        TransactionResult(
            outcome=TransactionOutcome.COMPLETED,
            message="ok",
            product=Product("A1", "Water", Money("1.00")),
            paid=Money("2.00"),
            price=Money("1.00"),
            change={Coin.DOLLAR: 1},
        )
    )
    assert "Receipt" in complete_receipt
    assert receipt(TransactionResult(TransactionOutcome.CANCELLED, "x")) == "x"

    config = load_config(tmp_path / "config.toml")
    runtime = Namespace(
        transactions=InMemoryTransactionRepository(),
        algorithm=get_change_algorithm("greedy"),
        config=config,
    )
    report_text = make_report("inventory", _state(), runtime, "plain")
    assert "items" in report_text
