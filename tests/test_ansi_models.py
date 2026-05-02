"""Test ANSI models."""

from datetime import UTC, datetime

import pytest

from vending.ansi import ANSI
from vending.models import (
    Coin,
    InventoryItem,
    MachineState,
    MachineStats,
    Mode,
    Product,
    Transaction,
    TransactionOutcome,
)
from vending.money import Money


def test_ansi_wrap_and_color_helpers() -> None:
    ansi = ANSI(enabled=True)
    assert ansi.wrap("x", "31") == "\033[31mx\033[0m"
    assert "\033[" in ansi.green("ok")
    assert "\033[" in ansi.yellow("ok")
    assert "\033[" in ansi.red("ok")
    assert "\033[" in ansi.dim("ok")
    assert "\033[" in ansi.bright("ok")

    plain = ANSI(enabled=False)
    assert plain.wrap("x", "31") == "x"
    assert plain.green("ok") == "ok"


def test_coin_helpers_and_token_parse() -> None:
    ordered = Coin.ordered_desc()
    assert ordered[0] == Coin.TWENTY
    assert ordered[-1] == Coin.PENNY
    assert Coin.from_token("q") == Coin.QUARTER
    assert str(Coin.DIME) == "dime"


def test_product_inventory_machine_stats_and_transaction_round_trip() -> None:
    product = Product("a1", "Water", Money("1.25"), "drink")
    product2 = Product.from_dict(product.to_dict())
    assert product2.slot == "A1"
    assert product2.price == Money("1.25")

    item = InventoryItem(product2, quantity=1, par_level=2)
    assert item.is_low is True
    assert item.is_empty is False
    item2 = InventoryItem.from_dict(item.to_dict())
    assert item2.quantity == 1
    assert item2.par_level == 2

    stats = MachineStats()
    parsed = datetime.fromisoformat(stats.started_at)
    assert parsed.tzinfo == UTC
    stats2 = MachineStats.from_dict(stats.to_dict())
    assert stats2.transactions == 0
    assert stats2.revenue == Money.zero()

    state = MachineState(
        inventory={"A1": item2},
        cash_reserves={Coin.QUARTER: 4},
        pending_inserted={Coin.DIME: 1},
        current_balance=Money("0.10"),
        mode=Mode.NORMAL,
    )
    assert state.cash_total == Money("1.00")
    assert state.pending_total == Money("0.10")

    tx = Transaction(
        started_at="2026-01-01T00:00:00+00:00",
        coins_inserted={Coin.QUARTER: 5},
        slot_selected="A1",
        outcome=TransactionOutcome.COMPLETED,
        change_returned={Coin.QUARTER: 1},
        completed_at="2026-01-01T00:00:01+00:00",
        message="done",
        paid=Money("1.25"),
        price=Money("1.00"),
        product_name="Water",
    )
    tx2 = Transaction.from_dict(tx.to_dict())
    assert tx2.slot_selected == "A1"
    assert tx2.price == Money("1.00")
    assert tx2.change_returned[Coin.QUARTER] == 1


def test_inventory_item_from_dict_rejects_non_mapping_product() -> None:
    with pytest.raises(TypeError):
        InventoryItem.from_dict({"product": "bad", "quantity": 1, "par_level": 1})
