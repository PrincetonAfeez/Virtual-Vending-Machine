"""Targeted tests to cover branches omitted by the main suites."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from vending.change import (
    GreedyChangeAlgorithm,
    OptimalChangeAlgorithm,
    denomination_value,
    get_change_algorithm,
)
from vending.models import (
    Coin,
    InventoryItem,
    MachineState,
    Mode,
    Product,
    Transaction,
    TransactionOutcome,
)
from vending.money import Money
from vending.persistence import load_inventory
from vending.renderers import ClassicRenderer, get_renderer
from vending.reports import (
    _format_csv,
    _format_inline,
    _format_plain,
    audit_report,
    format_report,
    sales_report,
)
from vending.repositories import JsonlTransactionRepository
from vending.simulation import run_simulation
from vending.state import build_initial_state, insert_coin, select_product


def test_denomination_value_coerces_int_like() -> None:
    class D:
        value = 5

    assert denomination_value(D()).cents == 5


def test_greedy_change_negative_and_zero_and_skip_zero_value() -> None:
    g = GreedyChangeAlgorithm()
    assert g.make_change(Money("-0.01"), {Coin.QUARTER: 1}) is None
    assert g.make_change(Money.zero(), {Coin.QUARTER: 1}) == {}

    class Bad:
        value = Money.zero()

    assert g.make_change(Money("0.05"), {Bad(): 10, Coin.NICKEL: 1}) == {Coin.NICKEL: 1}


def test_optimal_change_negative_zero_and_skip_zero_value() -> None:
    o = OptimalChangeAlgorithm()
    assert o.make_change(Money("-0.01"), {Coin.QUARTER: 1}) is None
    assert o.make_change(Money.zero(), {Coin.QUARTER: 1}) == {}

    class Bad:
        value = Money.zero()

    assert o.make_change(Money("0.05"), {Bad(): 10, Coin.NICKEL: 1}) == {Coin.NICKEL: 1}


def test_get_change_algorithm_unknown() -> None:
    with pytest.raises(ValueError, match="unknown change algorithm"):
        get_change_algorithm("nope")


def test_get_change_algorithm_optimal_branch() -> None:
    assert isinstance(get_change_algorithm(" optimal "), OptimalChangeAlgorithm)


def test_greedy_hits_zero_value_continue_only_bad_reserve() -> None:
    class Bad:
        value = Money.zero()

    assert GreedyChangeAlgorithm().make_change(Money("0.05"), {Bad(): 10}) is None


def test_money_operators_and_formatting() -> None:
    m = Money("1.00")
    with pytest.raises(TypeError):
        m + "x"  # type: ignore[operator]
    with pytest.raises(TypeError):
        _ = 1 + m  # type: ignore[operator]
    assert 0 + m == m
    assert -m == Money("-1.00")
    assert 3 * m == Money("3.00")
    assert m * 2 == Money("2.00")
    assert format(Money("2.50"), "") == "$2.50"
    assert str(Money("1.00")) == "$1.00"
    assert "Money(" in repr(Money("1.00"))
    assert format(Money("1.25"), ".2f") == "1.25"


def test_transaction_from_dict_coerces_bad_mapping_fields() -> None:
    tx = Transaction.from_dict(
        {
            "started_at": "2026-01-01T00:00:00+00:00",
            "coins_inserted": "not-a-mapping",
            "slot_selected": "A1",
            "outcome": "completed",
            "change_returned": 123,
            "completed_at": "2026-01-01T00:00:01+00:00",
            "message": "ok",
        }
    )
    assert tx.coins_inserted == {}
    assert tx.change_returned == {}


def test_load_inventory_skips_unknown_slots(tmp_path: Path) -> None:
    products = tmp_path / "p.json"
    products.write_text(
        json.dumps([{"slot": "A1", "name": "W", "price": "1.00", "quantity": 1, "par_level": 1}]),
        encoding="utf-8",
    )
    inv = tmp_path / "i.json"
    inv.write_text(
        json.dumps(
            [
                {"slot": "A1", "quantity": 2, "par_level": 1},
                {"slot": "Z9", "quantity": 99, "par_level": 1},
            ]
        ),
        encoding="utf-8",
    )
    merged = load_inventory(products, inv)
    assert merged["A1"].quantity == 2
    assert "Z9" not in merged


def test_default_products_data_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    import vending.persistence as pers

    monkeypatch.setattr(pers.json, "loads", lambda _s: {"not": "a list"})
    with pytest.raises(ValueError, match="default products must be a list"):
        pers.default_products_data()


def test_get_renderer_unknown() -> None:
    with pytest.raises(ValueError, match="unknown renderer"):
        get_renderer("neon")


def test_sales_report_group_by_variants() -> None:
    txs = [
        Transaction(
            started_at="2026-01-01T00:00:00+00:00",
            coins_inserted={},
            slot_selected="A1",
            outcome=TransactionOutcome.COMPLETED,
            change_returned={},
            completed_at="2026-01-01T02:00:00+00:00",
            message="ok",
            price=Money("1.00"),
        ),
        Transaction(
            started_at="2026-01-01T00:00:00+00:00",
            coins_inserted={},
            slot_selected=None,
            outcome=TransactionOutcome.COMPLETED,
            change_returned={},
            completed_at="2026-01-01T03:00:00+00:00",
            message="ok",
            price=Money("2.00"),
        ),
    ]
    hour = sales_report(txs, "hour")
    assert "by_hour" in hour
    slot = sales_report(txs, "slot")
    assert "unknown" in slot["by_slot"]
    weird = sales_report(txs, "other")
    assert "all" in weird["by_other"]


def test_audit_report_detects_issues() -> None:
    product = Product("A1", "W", Money("1.00"))
    item = InventoryItem(product, quantity=-1, par_level=1)
    state = MachineState(
        inventory={"A1": item},
        cash_reserves={Coin.QUARTER: -1},
        pending_inserted={},
        current_balance=Money("1.00"),
        mode=Mode.NORMAL,
    )
    report = audit_report(state)
    assert report["ok"] is False
    assert len(report["issues"]) >= 3


def test_format_report_plain_nested_and_csv_nested_dict() -> None:
    nested = format_report({"outer": {"inner": 1}}, "plain")
    assert "outer" in nested
    csv_out = format_report({"by_day": {"2026-01-01": {"count": 1, "revenue": "1.00"}}}, "csv")
    assert "count" in csv_out
    assert format_report({"items": []}, "csv") == ""
    assert "scalar" in _format_plain("scalar", 0)
    assert _format_inline(42) == "42"


def test_format_csv_fallback_single_row_dict() -> None:
    csv_out = _format_csv({"total": "1.00", "note": "x"})
    assert "total" in csv_out


def test_classic_renderer_stock_status_colors() -> None:
    p = Product("A1", "X", Money("1.00"))
    state = build_initial_state(
        {
            "A1": InventoryItem(p, quantity=0, par_level=2),
            "B1": InventoryItem(Product("B1", "Y", Money("1.00")), quantity=1, par_level=2),
            "C1": InventoryItem(Product("C1", "Z", Money("1.00")), quantity=5, par_level=2),
        },
        {Coin.QUARTER: 4},
    )
    text = ClassicRenderer(no_color=True, algorithm=GreedyChangeAlgorithm()).render(state)
    assert "empty" in text
    assert "low" in text
    assert "full" in text


def test_jsonl_all_when_file_removed_after_init(tmp_path: Path) -> None:
    path = tmp_path / "gone.jsonl"
    repo = JsonlTransactionRepository(path)
    path.unlink()
    assert repo.all() == []


def test_jsonl_repository_skips_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    path.write_text("\n\n", encoding="utf-8")
    repo = JsonlTransactionRepository(path)
    assert repo.all() == []


def test_run_simulation_records_exception_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    product = Product("A1", "W", Money("0.50"))
    state = build_initial_state({"A1": InventoryItem(product, 5, 2)}, {Coin.QUARTER: 20})

    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("simulated")

    monkeypatch.setattr("vending.simulation.insert_coin", boom)
    result = run_simulation(state, customers=1, seed=0)
    assert "RuntimeError" in result.summary["outcomes"]


def test_select_product_machine_locked() -> None:
    product = Product("A1", "W", Money("1.00"))
    state = build_initial_state({"A1": InventoryItem(product, 1, 1)}, {Coin.QUARTER: 4})
    state = insert_coin(state, Coin.QUARTER)
    state = insert_coin(state, Coin.QUARTER)
    state = insert_coin(state, Coin.QUARTER)
    state = insert_coin(state, Coin.QUARTER)
    locked = replace(state, mode=Mode.LOCKED)
    new_state, res = select_product(locked, "A1", GreedyChangeAlgorithm())
    assert res.outcome == TransactionOutcome.MACHINE_LOCKED
    assert new_state.mode == Mode.LOCKED
