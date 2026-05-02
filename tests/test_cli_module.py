"""Unit tests for ``vending.cli`` so coverage includes the CLI module."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from vending.cli import (
    append_transaction,
    build_parser,
    build_runtime,
    command_audit,
    command_help,
    command_report,
    command_reset,
    command_restock,
    command_simulate,
    handle_customer_command,
    handle_service_command,
    interactive,
    main,
    make_report,
    persist,
    receipt,
)
from vending.exceptions import VendingError
from vending.models import Coin, Product, Transaction, TransactionOutcome, TransactionResult
from vending.money import Money
from vending.persistence import load_config, load_state
from vending.state import enter_service_mode, insert_coin


def _runtime(tmp_path: Path, *cli_tail: str):
    cfg = tmp_path / "config.toml"
    st = tmp_path / "state.json"
    args = build_parser().parse_args(
        ["--config", str(cfg), "--state-file", str(st), *cli_tail]
    )
    return build_runtime(args), args


def test_build_runtime_persist_append_transaction(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, _ = _runtime(tmp_path, "audit")
    state = load_state(runtime.config, runtime.state_file)
    persist(runtime, state)
    append_transaction(
        runtime,
        TransactionResult(TransactionOutcome.INSUFFICIENT_FUNDS, "x", transaction=None),
    )
    append_transaction(
        runtime,
        TransactionResult(
            TransactionOutcome.COMPLETED,
            "ok",
            product=Product("A1", "W", Money("1.00")),
            paid=Money("1.00"),
            price=Money("1.00"),
            change={},
            transaction=None,
        ),
    )
    capsys.readouterr()


def test_receipt_completed_without_product() -> None:
    text = receipt(
        TransactionResult(
            outcome=TransactionOutcome.COMPLETED,
            message="ok",
            product=None,
            paid=Money("1.00"),
            price=Money("1.00"),
            change={},
        )
    )
    assert "unknown" in text


def test_command_help_branches() -> None:
    assert "Service:" not in command_help(False)
    assert "Service:" in command_help(True)


def test_make_report_all_types_and_unknown(tmp_path: Path) -> None:
    runtime, _ = _runtime(tmp_path, "audit")
    state = load_state(runtime.config, runtime.state_file)
    for kind in ("sales", "inventory", "cash", "top-sellers", "failed"):
        text = make_report(kind, state, runtime, "plain")
        assert isinstance(text, str) and len(text) > 0
    assert "{" in make_report("inventory", state, runtime, "json")
    with pytest.raises(ValueError, match="unknown report"):
        make_report("nope", state, runtime, "plain")


@pytest.mark.parametrize(
    "cmd,expect_substr",
    [
        ("", ""),
        ("exit", ""),
        ("help", "Commands:"),
        ("balance", "Balance:"),
        ("cancel", ""),
        ("service", "usage: service"),
        ("q", "Inserted"),
        ("insert", "usage: insert"),
        ("insert quarter", "Inserted"),
        ("select", ""),
        ("A1", ""),
        ("nosuchverb", "Unknown command"),
    ],
)
def test_handle_customer_command_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], cmd: str, expect_substr: str
) -> None:
    runtime, _ = _runtime(tmp_path, "audit")
    state = load_state(runtime.config, runtime.state_file)
    state, keep = handle_customer_command(state, runtime, cmd)
    out = capsys.readouterr().out
    if expect_substr:
        assert expect_substr in out
    if cmd == "exit":
        assert keep is False
    else:
        assert keep is True


def test_handle_customer_bad_service_pin_raises(tmp_path: Path) -> None:
    runtime, _ = _runtime(tmp_path, "audit")
    state = load_state(runtime.config, runtime.state_file)
    with pytest.raises(VendingError):
        handle_customer_command(state, runtime, "service 0000")


def test_handle_customer_service_pin_success_and_select(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, _ = _runtime(tmp_path, "audit")
    state = load_state(runtime.config, runtime.state_file)
    pin = "1234"
    state, _ = handle_customer_command(state, runtime, f"service {pin}")
    assert "Service mode" in capsys.readouterr().out
    state, _ = handle_customer_command(state, runtime, "help")
    assert "Service:" in capsys.readouterr().out
    state, _ = handle_service_command(state, runtime, "exit-service")
    for _ in range(20):
        state = insert_coin(state, Coin.QUARTER, runtime.config.max_balance)
    state, _ = handle_customer_command(state, runtime, "select A1")
    out = capsys.readouterr().out
    assert "Receipt" in out or "Insert" in out


def test_handle_service_command_full_menu(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, _ = _runtime(tmp_path, "audit")
    state = load_state(runtime.config, runtime.state_file)
    state = enter_service_mode(state, "1234", runtime.config.service_pin_hash)

    state, _ = handle_service_command(state, runtime, "")
    assert capsys.readouterr().out == ""

    state, _ = handle_service_command(state, runtime, "help")
    assert "Service:" in capsys.readouterr().out

    state, _ = handle_service_command(state, runtime, "exit-service")
    state = enter_service_mode(state, "1234", runtime.config.service_pin_hash)

    state, _ = handle_service_command(state, runtime, "mode")
    assert "Mode: service" in capsys.readouterr().out

    state, _ = handle_service_command(state, runtime, "restock A1 1")
    state, _ = handle_service_command(state, runtime, "restock-all")
    state, _ = handle_service_command(state, runtime, "withdraw 20.00")
    state, _ = handle_service_command(state, runtime, "withdraw")
    state, _ = handle_service_command(state, runtime, "set-price A1 1.50")
    state, _ = handle_service_command(
        state, runtime, 'add-product B1 "Chips" 2.00 snack 3 4'
    )
    state, _ = handle_service_command(state, runtime, "remove-product B1")
    state, _ = handle_service_command(state, runtime, "set-par A1 5")
    state, _ = handle_service_command(state, runtime, "report inventory")
    state, _ = handle_service_command(state, runtime, "audit-log")
    state, _ = handle_service_command(state, runtime, "lock")
    state, _ = handle_service_command(state, runtime, "unlock 1234")
    assert capsys.readouterr().out


def test_handle_service_audit_log_prints_transactions(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, _ = _runtime(tmp_path, "audit")
    state = load_state(runtime.config, runtime.state_file)
    state = enter_service_mode(state, "1234", runtime.config.service_pin_hash)
    tx = Transaction(
        started_at="2026-01-01T00:00:00+00:00",
        coins_inserted={},
        slot_selected="A1",
        outcome=TransactionOutcome.COMPLETED,
        change_returned={},
        completed_at="2026-01-01T00:00:01+00:00",
        message="sold",
    )
    runtime.transactions.append(tx)
    state, _ = handle_service_command(state, runtime, "audit-log")
    out = capsys.readouterr().out
    assert "completed" in out
    assert "A1" in out


def test_handle_service_add_product_defaults_and_unlock_getpass(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, _ = _runtime(tmp_path, "audit")
    state = load_state(runtime.config, runtime.state_file)
    state = enter_service_mode(state, "1234", runtime.config.service_pin_hash)
    state, _ = handle_service_command(state, runtime, "add-product C1 Gum 0.75")
    assert "Added" in capsys.readouterr().out
    state, _ = handle_service_command(state, runtime, "lock")
    monkeypatch.setattr("vending.cli.getpass.getpass", lambda prompt="": "1234")
    state, _ = handle_service_command(state, runtime, "unlock")
    assert "unlocked" in capsys.readouterr().out.lower()


def test_command_report_variants(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    runtime, _ = _runtime(tmp_path, "audit")
    base = [
        "--config",
        str(runtime.config.config_path),
        "--state-file",
        str(runtime.state_file),
        "report",
    ]
    for tail, fmt in [
        (["sales", "--by-day"], "json"),
        (["sales", "--by-slot"], "csv"),
        (["sales", "--by-hour"], "plain"),
        (["inventory"], "plain"),
        (["cash"], "json"),
        (["top-sellers", "--limit", "3"], "plain"),
        (["failed"], "plain"),
    ]:
        args = build_parser().parse_args([*base, *tail, "--format", fmt])
        assert command_report(args, runtime) == 0
        assert capsys.readouterr().out


def test_command_restock_and_simulate_and_audit(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, _ = _runtime(tmp_path, "audit")
    args = build_parser().parse_args(
        [
            "--config",
            str(runtime.config.config_path),
            "--state-file",
            str(runtime.state_file),
            "restock",
            "A1",
            "2",
            "--pin",
            "1234",
        ]
    )
    assert command_restock(args, runtime) == 0
    args = build_parser().parse_args(
        [
            "--config",
            str(runtime.config.config_path),
            "--state-file",
            str(runtime.state_file),
            "restock",
            "--all",
            "--pin",
            "1234",
        ]
    )
    assert command_restock(args, runtime) == 0

    args = build_parser().parse_args(
        [
            "--config",
            str(runtime.config.config_path),
            "--state-file",
            str(runtime.state_file),
            "simulate",
            "--customers",
            "2",
            "--seed",
            "1",
        ]
    )
    assert command_simulate(args, runtime) == 0
    assert "customers:" in capsys.readouterr().out

    args = build_parser().parse_args(
        [
            "--config",
            str(runtime.config.config_path),
            "--state-file",
            str(runtime.state_file),
            "simulate",
            "--customers",
            "1",
            "--seed",
            "2",
            "--format",
            "json",
        ]
    )
    assert command_simulate(args, runtime) == 0
    assert capsys.readouterr().out.strip().startswith("{")

    assert command_audit(runtime) in (0, 1)


def test_command_audit_fails_when_report_not_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, _ = _runtime(tmp_path, "audit")
    monkeypatch.setattr("vending.cli.audit_report", lambda _state: {"ok": False, "issues": ["x"]})
    assert command_audit(runtime) == 1


def test_command_restock_usage_exits(tmp_path: Path) -> None:
    runtime, _ = _runtime(tmp_path, "audit")
    args = build_parser().parse_args(
        [
            "--config",
            str(runtime.config.config_path),
            "--state-file",
            str(runtime.state_file),
            "restock",
            "--pin",
            "1234",
        ]
    )
    with pytest.raises(SystemExit, match="usage"):
        command_restock(args, runtime)


def test_command_reset_paths(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, _ = _runtime(tmp_path, "audit")
    args = build_parser().parse_args(
        [
            "--config",
            str(runtime.config.config_path),
            "--state-file",
            str(runtime.state_file),
            "reset",
        ]
    )
    with pytest.raises(SystemExit, match="--factory"):
        command_reset(args, runtime)

    args = build_parser().parse_args(
        [
            "--config",
            str(runtime.config.config_path),
            "--state-file",
            str(runtime.state_file),
            "reset",
            "--factory",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _: "NOPE")
    assert command_reset(args, runtime) == 1
    assert "cancelled" in capsys.readouterr().out.lower()

    monkeypatch.setattr("builtins.input", lambda _: "RESET")
    assert command_reset(args, runtime) == 0

    cfg = runtime.config.config_path
    alt = tmp_path / "alt-state.json"
    alt.write_text("{}", encoding="utf-8")
    args = build_parser().parse_args(
        [
            "--config",
            str(cfg),
            "--state-file",
            str(alt),
            "reset",
            "--factory",
            "--yes",
        ]
    )
    rt = build_runtime(args)
    assert command_reset(args, rt) == 0


def test_main_subcommands_and_errors(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = tmp_path / "config.toml"
    load_config(cfg)
    st = tmp_path / "state.json"

    monkeypatch.setattr("vending.cli.interactive", lambda rt, start_service=False: 0)
    assert main(["--config", str(cfg), "--state-file", str(st), "run"]) == 0
    assert main(["--config", str(cfg), "--state-file", str(st), "admin"]) == 0

    def boom_report(_a: Namespace, _r: object) -> int:
        raise VendingError("bad")

    monkeypatch.setattr("vending.cli.command_report", boom_report)
    r = main(["--config", str(cfg), "--state-file", str(st), "report", "inventory"])
    assert r == 2
    assert "bad" in capsys.readouterr().err

    monkeypatch.setattr("vending.cli.command_report", command_report)
    assert main(["--config", str(cfg), "--state-file", str(st), "report", "cash"]) == 0

    monkeypatch.setattr("vending.cli.command_simulate", lambda a, r: 0)
    assert (
        main(
            [
                "--config",
                str(cfg),
                "--state-file",
                str(st),
                "simulate",
                "--customers",
                "1",
            ]
        )
        == 0
    )

    monkeypatch.setattr("vending.cli.command_audit", lambda r: 0)
    assert main(["--config", str(cfg), "--state-file", str(st), "audit"]) == 0

    monkeypatch.setattr("vending.cli.command_restock", lambda a, r: 0)
    assert (
        main(
            [
                "--config",
                str(cfg),
                "--state-file",
                str(st),
                "restock",
                "A1",
                "1",
                "--pin",
                "1234",
            ]
        )
        == 0
    )

    fake_ns = Namespace(
        command="__not_a_command__",
        config=str(cfg),
        state_file=str(st),
        algorithm="greedy",
        renderer="classic",
        no_color=True,
        type="inventory",
        by_day=False,
        by_slot=False,
        by_hour=False,
        format="plain",
        limit=10,
        slot=None,
        quantity=None,
        all=False,
        pin=None,
        customers=1,
        seed=1,
        factory=False,
        yes=False,
    )
    class FakeParser:
        def parse_args(self, argv: list[str] | None = None) -> Namespace:
            return fake_ns

        def print_help(self, file: object | None = None) -> None:
            print("usage: vending", file=file)

    monkeypatch.setattr("vending.cli.build_parser", lambda: FakeParser())
    assert main([]) == 1
    assert "usage" in capsys.readouterr().out.lower()


def test_interactive_loop_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, _ = _runtime(tmp_path, "audit")
    seq = iter(["service 0000", "balance", "exit"])

    def fake_input(_prompt: str = "") -> str:
        return next(seq)

    monkeypatch.setattr("builtins.input", fake_input)
    assert interactive(runtime) == 0
    out = capsys.readouterr().out
    assert "Error:" in out or "Balance" in out


def test_interactive_keyboard_interrupt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, _ = _runtime(tmp_path, "audit")

    def boom(_: str = "") -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", boom)
    assert interactive(runtime) == 0
    assert "Exiting" in capsys.readouterr().out


def test_main_uses_run_when_no_subcommand_given(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = tmp_path / "config.toml"
    load_config(cfg)
    st = tmp_path / "state.json"
    calls: list[bool] = []

    def capture_interactive(rt: object, start_service: bool = False) -> int:
        calls.append(start_service)
        return 0

    monkeypatch.setattr("vending.cli.interactive", capture_interactive)
    assert main(["--config", str(cfg), "--state-file", str(st)]) == 0
    assert calls == [False]


def test_main_reset_factory_yes_invokes_command_reset(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    load_config(cfg)
    st = tmp_path / "state.json"
    assert (
        main(
            [
                "--config",
                str(cfg),
                "--state-file",
                str(st),
                "reset",
                "--factory",
                "--yes",
            ]
        )
        == 0
    )


def test_interactive_admin_mode(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, _ = _runtime(tmp_path, "audit")
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "1234")
    seq = iter(["exit-service", "exit"])

    def fake_input(_prompt: str = "") -> str:
        return next(seq)

    monkeypatch.setattr("builtins.input", fake_input)
    assert interactive(runtime, start_service=True) == 0
    assert capsys.readouterr().out
