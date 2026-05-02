"""Test reports, renderers, and simulation."""

import random

from vending.change import GreedyChangeAlgorithm
from vending.models import Coin, InventoryItem, Product, Transaction, TransactionOutcome
from vending.money import Money
from vending.renderers import ClassicRenderer, CompactRenderer, MinimalRenderer, get_renderer
from vending.reports import (
    audit_report,
    cash_report,
    failed_report,
    format_report,
    inventory_report,
    sales_report,
    top_sellers_report,
)
from vending.simulation import (
    BudgetCustomer,
    ExactChangeCustomer,
    PickyCustomer,
    RandomCustomer,
    run_simulation,
)
from vending.state import build_initial_state, insert_coin


def _state():
    product = Product("A1", "Water Bottle", Money("1.25"), "drink")
    inventory = {"A1": InventoryItem(product, quantity=3, par_level=2)}
    return build_initial_state(inventory, {Coin.QUARTER: 10, Coin.DIME: 10})


def _transactions() -> list[Transaction]:
    return [
        Transaction(
            started_at="2026-01-01T00:00:00+00:00",
            coins_inserted={Coin.DOLLAR: 2},
            slot_selected="A1",
            outcome=TransactionOutcome.COMPLETED,
            change_returned={Coin.QUARTER: 3},
            completed_at="2026-01-01T01:00:00+00:00",
            message="ok",
            paid=Money("2.00"),
            price=Money("1.25"),
            product_name="Water Bottle",
        ),
        Transaction(
            started_at="2026-01-01T00:01:00+00:00",
            coins_inserted={Coin.QUARTER: 1},
            slot_selected="A1",
            outcome=TransactionOutcome.CANCELLED,
            change_returned={Coin.QUARTER: 1},
            completed_at="2026-01-01T02:00:00+00:00",
            message="cancelled",
            paid=Money("0.25"),
            price=Money.zero(),
            product_name=None,
        ),
    ]


def test_reports_cover_grouping_and_formatting_paths() -> None:
    txs = _transactions()
    by_day = sales_report(txs, "day")
    assert by_day["completed_count"] == 1
    assert "by_day" in by_day

    inv = inventory_report(_state().inventory)
    assert inv["items"][0]["slot"] == "A1"

    cash = cash_report(_state())
    assert cash["total"] == "3.50"

    top = top_sellers_report(txs, limit=5)
    assert top["top_sellers"][0]["product"] == "Water Bottle"

    failed = failed_report(txs)
    assert failed["failed_count"] == 1

    assert format_report(inv, "plain")
    assert format_report(inv, "json").startswith("{")
    assert "slot" in format_report(inv, "csv")


def test_audit_report_renderer_and_get_renderer_paths() -> None:
    state = _state()
    state = insert_coin(state, Coin.QUARTER)
    audit = audit_report(state)
    assert audit["ok"] is True

    classic = ClassicRenderer(no_color=True, algorithm=GreedyChangeAlgorithm()).render(state)
    compact = CompactRenderer(no_color=True, algorithm=GreedyChangeAlgorithm()).render(state)
    minimal = MinimalRenderer().render(state)
    assert "VIRTUAL VENDING MACHINE" in classic
    assert "slot product" in compact
    assert minimal.startswith("normal|")
    assert isinstance(get_renderer("classic"), ClassicRenderer)
    assert isinstance(get_renderer("compact"), CompactRenderer)
    assert isinstance(get_renderer("minimal"), MinimalRenderer)


def test_customer_types_and_run_simulation() -> None:
    state = _state()
    rng = random.Random(7)
    product = RandomCustomer().choose_product(state, rng)
    assert product is not None
    assert BudgetCustomer().choose_product(state, rng) is not None
    assert PickyCustomer(("drink",)).choose_product(state, rng) is not None
    assert ExactChangeCustomer().choose_product(state, rng) is not None

    assert RandomCustomer().choose_coins(product, rng)
    assert BudgetCustomer().choose_coins(product, rng)
    assert PickyCustomer().choose_coins(product, rng)
    assert ExactChangeCustomer().choose_coins(product, rng)

    result = run_simulation(state, customers=8, seed=10, algorithm=GreedyChangeAlgorithm())
    assert result.summary["customers"] == 8
    assert isinstance(result.transactions, tuple)
