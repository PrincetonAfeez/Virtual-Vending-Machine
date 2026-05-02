"""Test state."""

from dataclasses import FrozenInstanceError

import pytest

from vending.change import GreedyChangeAlgorithm
from vending.exceptions import ServiceModeRequiredError
from vending.models import Coin, InventoryItem, Mode, Product, TransactionOutcome
from vending.money import Money
from vending.state import (
    build_initial_state,
    enter_service_mode,
    insert_coin,
    restock_slot,
    select_product,
)


def sample_state(reserves: dict[Coin, int] | None = None):
    product = Product("A1", "Water", Money("1.25"), "drink")
    inventory = {"A1": InventoryItem(product, quantity=2, par_level=1)}
    return build_initial_state(inventory, {Coin.QUARTER: 8} if reserves is None else reserves)


def test_state_is_frozen_and_mappings_are_read_only() -> None:
    state = sample_state()
    with pytest.raises(FrozenInstanceError):
        state.current_balance = Money("1.00")  # type: ignore[misc]
    with pytest.raises(TypeError):
        state.inventory["A1"] = state.inventory["A1"]  # type: ignore[index]


def test_insert_coin_returns_new_state() -> None:
    state = sample_state()
    updated = insert_coin(state, Coin.QUARTER)
    assert state.current_balance == Money.zero()
    assert updated.current_balance == Money("0.25")
    assert updated.pending_inserted[Coin.QUARTER] == 1


def test_successful_purchase_decrements_inventory_and_commits_cash() -> None:
    state = sample_state({Coin.QUARTER: 4})
    state = insert_coin(state, Coin.DOLLAR)
    state = insert_coin(state, Coin.DOLLAR)

    state, result = select_product(state, "A1", GreedyChangeAlgorithm())

    assert result.outcome == TransactionOutcome.COMPLETED
    assert state.inventory["A1"].quantity == 1
    assert state.current_balance == Money.zero()
    assert result.change == {Coin.QUARTER: 3}
    assert state.cash_reserves[Coin.DOLLAR] == 2
    assert state.stats.successful == 1


def test_cannot_make_change_refunds_inserted_money() -> None:
    state = sample_state({})
    state = insert_coin(state, Coin.DOLLAR)
    state = insert_coin(state, Coin.DOLLAR)

    state, result = select_product(state, "A1", GreedyChangeAlgorithm())

    assert result.outcome == TransactionOutcome.EXACT_CHANGE_REQUIRED
    assert result.change == {Coin.DOLLAR: 2}
    assert state.current_balance == Money.zero()
    assert state.pending_inserted == {}
    assert all(count == 0 for count in state.cash_reserves.values())


def test_service_commands_require_service_mode() -> None:
    state = sample_state()
    with pytest.raises(ServiceModeRequiredError):
        restock_slot(state, "A1", 2)


def test_enter_service_mode_with_pin_hash() -> None:
    from vending.state import hash_pin

    state = enter_service_mode(sample_state(), "1234", hash_pin("1234"))
    assert state.mode == Mode.SERVICE
