"""Command-line interface for the virtual vending machine."""

from __future__ import annotations

import argparse
import getpass
import shlex
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from vending.change import ChangeAlgorithm, get_change_algorithm
from vending.exceptions import VendingError
from vending.models import Coin, MachineState, Mode, TransactionOutcome, TransactionResult
from vending.money import Money
from vending.persistence import Config, load_config, load_state, reset_factory, save_state_atomic
from vending.renderers import Renderer, get_renderer
from vending.reports import (
    audit_report,
    cash_report,
    failed_report,
    format_report,
    inventory_report,
    sales_report,
    top_sellers_report,
)
from vending.repositories import JsonlTransactionRepository
from vending.simulation import run_simulation
from vending.state import (
    add_product,
    cancel_transaction,
    enter_service_mode,
    exit_service_mode,
    format_change,
    insert_coin,
    lock_machine,
    remove_product,
    restock_all_to_par,
    restock_slot,
    select_product,
    set_par_level,
    set_price,
    unlock_machine,
    withdraw_cash,
)


@dataclass(slots=True)
class Runtime:
    config: Config
    state_file: Path
    algorithm_name: str
    algorithm: ChangeAlgorithm[Coin]
    renderer: Renderer
    transactions: JsonlTransactionRepository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vending")
    parser.add_argument("--config", help="Path to config.toml")
    parser.add_argument("--renderer", choices=["classic", "compact", "minimal"])
    parser.add_argument("--no-color", action="store_true")
    parser.add_argument("--state-file", help="Override persisted state file")
    parser.add_argument("--algorithm", choices=["greedy", "optimal"])

    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("run", help="Start the interactive vending machine")
    subparsers.add_parser("admin", help="Start directly in service mode")

    report = subparsers.add_parser("report", help="Generate an operator report")
    report.add_argument("type", choices=["sales", "inventory", "cash", "top-sellers", "failed"])
    report.add_argument("--by-day", action="store_true")
    report.add_argument("--by-slot", action="store_true")
    report.add_argument("--by-hour", action="store_true")
    report.add_argument("--limit", type=int, default=10)
    report.add_argument("--format", choices=["plain", "json", "csv"], default="plain")

    restock = subparsers.add_parser("restock", help="Restock from the command line")
    restock.add_argument("slot", nargs="?")
    restock.add_argument("quantity", nargs="?", type=int)
    restock.add_argument("--all", action="store_true")
    restock.add_argument("--pin")

    simulate = subparsers.add_parser("simulate", help="Run simulated customers")
    simulate.add_argument("--customers", type=int, default=100)
    simulate.add_argument("--seed", type=int)
    simulate.add_argument("--format", choices=["plain", "json"], default="plain")

    subparsers.add_parser("audit", help="Check persisted state integrity")

    reset = subparsers.add_parser("reset", help="Restore bundled defaults")
    reset.add_argument("--factory", action="store_true")
    reset.add_argument("--yes", action="store_true")
    return parser


def build_runtime(args: argparse.Namespace) -> Runtime:
    config = load_config(args.config)
    state_file = Path(args.state_file).expanduser() if args.state_file else config.state_file
    algorithm_name = args.algorithm or config.algorithm
    algorithm = get_change_algorithm(algorithm_name)
    renderer = get_renderer(args.renderer or config.renderer, args.no_color, algorithm)
    return Runtime(
        config=config,
        state_file=state_file,
        algorithm_name=algorithm_name,
        algorithm=algorithm,
        renderer=renderer,
        transactions=JsonlTransactionRepository(config.transactions_file),
    )


def persist(runtime: Runtime, state: MachineState) -> None:
    save_state_atomic(state, runtime.state_file)


def append_transaction(runtime: Runtime, result: TransactionResult) -> None:
    if result.transaction is not None:
        runtime.transactions.append(result.transaction)


def receipt(result: TransactionResult) -> str:
    if result.outcome != TransactionOutcome.COMPLETED:
        return result.message
    product = result.product
    lines = [
        "",
        "Receipt",
        "-------",
        f"Product: {product.name if product else 'unknown'}",
        f"Price:   {result.price:currency}",
        f"Paid:    {result.paid:currency}",
        f"Change:  {format_change(result.change)}",
    ]
    return "\n".join(lines)


def command_help(service: bool = False) -> str:
    customer = (
        "Commands: insert <coin>, p/n/d/q/$ shortcuts, select <slot>, direct slot code, "
        "cancel, balance, service <pin>, help, exit"
    )
    if not service:
        return customer
    return (
        customer
        + "\nService: restock <slot> <qty>, restock-all, withdraw [keep], "
        "set-price <slot> <price>, "
        "add-product <slot> <name> <price> [category] [qty] [par], remove-product <slot>, "
        "set-par <slot> <level>, report <type>, audit-log, lock, unlock <pin>, exit-service"
    )


def handle_customer_command(
    state: MachineState, runtime: Runtime, command: str
) -> tuple[MachineState, bool]:
    tokens = shlex.split(command)
    if not tokens:
        return state, True
    verb = tokens[0].lower()

    if verb in {"exit", "quit"}:
        return state, False
    if verb == "help":
        print(command_help(state.mode == Mode.SERVICE))
        return state, True
    if verb == "balance":
        print(f"Balance: {state.current_balance:currency}")
        return state, True
    if verb == "cancel":
        state, result = cancel_transaction(state)
        append_transaction(runtime, result)
        print(result.message)
        return state, True
    if verb == "service":
        if len(tokens) < 2:
            print("usage: service <pin>")
            return state, True
        state = enter_service_mode(state, tokens[1], runtime.config.service_pin_hash)
        print(state.last_message)
        return state, True
    if verb in {"p", "n", "d", "q", "$"}:
        state = insert_coin(state, Coin.from_token(verb), runtime.config.max_balance)
        print(state.last_message)
        return state, True
    if verb == "insert":
        if len(tokens) < 2:
            print("usage: insert <coin>")
            return state, True
        state = insert_coin(state, Coin.from_token(tokens[1]), runtime.config.max_balance)
        print(state.last_message)
        return state, True
    if verb == "select" or (len(tokens) == 1 and len(tokens[0]) in {2, 3}):
        slot = tokens[1] if verb == "select" and len(tokens) > 1 else tokens[0]
        state, result = select_product(state, slot, runtime.algorithm)
        append_transaction(runtime, result)
        print(receipt(result))
        return state, True
    print("Unknown command. Type help.")
    return state, True


def handle_service_command(
    state: MachineState, runtime: Runtime, command: str
) -> tuple[MachineState, bool]:
    tokens = shlex.split(command)
    if not tokens:
        return state, True
    verb = tokens[0].lower()
    if verb not in {
        "restock",
        "restock-all",
        "withdraw",
        "set-price",
        "add-product",
        "remove-product",
        "set-par",
        "mode",
        "report",
        "audit-log",
        "lock",
        "unlock",
        "exit-service",
    }:
        return handle_customer_command(state, runtime, command)

    if verb == "exit-service":
        return exit_service_mode(state), True
    if verb == "mode":
        print(f"Mode: {state.mode.value}")
        return state, True
    if verb == "restock":
        state = restock_slot(state, tokens[1], int(tokens[2]))
        print(state.last_message)
        return state, True
    if verb == "restock-all":
        state = restock_all_to_par(state)
        print(state.last_message)
        return state, True
    if verb == "withdraw":
        keep = Money(tokens[1]) if len(tokens) > 1 else Money("20.00")
        state, withdrawn = withdraw_cash(state, keep)
        print(f"{state.last_message} {format_change(withdrawn)}")
        return state, True
    if verb == "set-price":
        state = set_price(state, tokens[1], Money(tokens[2]))
        print(state.last_message)
        return state, True
    if verb == "add-product":
        slot = tokens[1]
        name = tokens[2]
        price = Money(tokens[3])
        category = tokens[4] if len(tokens) > 4 else "snack"
        quantity = int(tokens[5]) if len(tokens) > 5 else 0
        par = int(tokens[6]) if len(tokens) > 6 else 5
        state = add_product(state, slot, name, price, category, quantity, par)
        print(state.last_message)
        return state, True
    if verb == "remove-product":
        state = remove_product(state, tokens[1])
        print(state.last_message)
        return state, True
    if verb == "set-par":
        state = set_par_level(state, tokens[1], int(tokens[2]))
        print(state.last_message)
        return state, True
    if verb == "report":
        report_type = tokens[1] if len(tokens) > 1 else "inventory"
        print(make_report(report_type, state, runtime, "plain"))
        return state, True
    if verb == "audit-log":
        for tx in runtime.transactions.all()[-10:]:
            print(f"{tx.completed_at} {tx.outcome.value} {tx.slot_selected or '-'} {tx.message}")
        return state, True
    if verb == "lock":
        state = lock_machine(state)
        print(state.last_message)
        return state, True
    if verb == "unlock":
        pin = tokens[1] if len(tokens) > 1 else getpass.getpass("Service PIN: ")
        state = unlock_machine(state, pin, runtime.config.service_pin_hash)
        print(state.last_message)
        return state, True
    raise AssertionError("unreachable")  # pragma: no cover


def interactive(runtime: Runtime, start_service: bool = False) -> int:
    state = load_state(runtime.config, runtime.state_file)
    if start_service:
        pin = getpass.getpass("Service PIN: ")
        state = enter_service_mode(state, pin, runtime.config.service_pin_hash)
    print(command_help(start_service))
    keep_running = True
    while keep_running:
        print()
        print(runtime.renderer.render(state))
        prompt = "service> " if state.mode == Mode.SERVICE else "vending> "
        try:
            command = input(prompt)
            if state.mode == Mode.SERVICE:
                state, keep_running = handle_service_command(state, runtime, command)
            else:
                state, keep_running = handle_customer_command(state, runtime, command)
            persist(runtime, state)
        except (VendingError, ValueError, IndexError) as exc:
            print(f"Error: {exc}")
        except KeyboardInterrupt:
            print("\nExiting.")
            break
    persist(runtime, state)
    return 0


def make_report(report_type: str, state: MachineState, runtime: Runtime, output_format: str) -> str:
    transactions = runtime.transactions.all()
    if report_type == "sales":
        return format_report(sales_report(transactions), output_format)
    if report_type == "inventory":
        return format_report(inventory_report(state.inventory), output_format)
    if report_type == "cash":
        return format_report(cash_report(state), output_format)
    if report_type == "top-sellers":
        return format_report(top_sellers_report(transactions), output_format)
    if report_type == "failed":
        return format_report(failed_report(transactions), output_format)
    raise ValueError(f"unknown report: {report_type}")


def command_report(args: argparse.Namespace, runtime: Runtime) -> int:
    state = load_state(runtime.config, runtime.state_file)
    transactions = runtime.transactions.all()
    group_by = None
    if args.by_day:
        group_by = "day"
    if args.by_slot:
        group_by = "slot"
    if args.by_hour:
        group_by = "hour"

    if args.type == "sales":
        report = sales_report(transactions, group_by)
    elif args.type == "inventory":
        report = inventory_report(state.inventory)
    elif args.type == "cash":
        report = cash_report(state)
    elif args.type == "top-sellers":
        report = top_sellers_report(transactions, args.limit)
    else:
        report = failed_report(transactions)
    print(format_report(report, args.format))
    return 0


def command_restock(args: argparse.Namespace, runtime: Runtime) -> int:
    pin = args.pin or getpass.getpass("Service PIN: ")
    state = enter_service_mode(
        load_state(runtime.config, runtime.state_file), pin, runtime.config.service_pin_hash
    )
    if args.all:
        state = restock_all_to_par(state)
    else:
        if not args.slot or args.quantity is None:
            raise SystemExit("usage: vending restock <slot> <quantity> [--pin PIN]")
        state = restock_slot(state, args.slot, args.quantity)
    state = exit_service_mode(state)
    persist(runtime, state)
    print(state.last_message)
    return 0


def command_simulate(args: argparse.Namespace, runtime: Runtime) -> int:
    state = load_state(runtime.config, runtime.state_file)
    result = run_simulation(
        state, customers=args.customers, seed=args.seed, algorithm=runtime.algorithm
    )
    for transaction in result.transactions:
        runtime.transactions.append(transaction)
    persist(runtime, result.state)
    if args.format == "json":
        import json

        print(json.dumps(result.summary, indent=2))
    else:
        for key, value in result.summary.items():
            print(f"{key}: {value}")
    return 0


def command_audit(runtime: Runtime) -> int:
    state = load_state(runtime.config, runtime.state_file)
    report = audit_report(state)
    print(format_report(report, "plain"))
    return 0 if report["ok"] else 1


def command_reset(args: argparse.Namespace, runtime: Runtime) -> int:
    if not args.factory:
        raise SystemExit("use --factory to restore bundled defaults")
    if not args.yes:
        confirm = input("Type RESET to restore defaults: ")
        if confirm != "RESET":
            print("Reset cancelled.")
            return 1
    reset_factory(runtime.config)
    if runtime.state_file != runtime.config.state_file and runtime.state_file.exists():
        runtime.state_file.unlink()
    print("Factory defaults restored.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        args.command = "run"
    runtime = build_runtime(args)

    try:
        if args.command == "run":
            return interactive(runtime)
        if args.command == "admin":
            return interactive(runtime, start_service=True)
        if args.command == "report":
            return command_report(args, runtime)
        if args.command == "restock":
            return command_restock(args, runtime)
        if args.command == "simulate":
            return command_simulate(args, runtime)
        if args.command == "audit":
            return command_audit(runtime)
        if args.command == "reset":
            return command_reset(args, runtime)
    except VendingError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    parser.print_help()
    return 1
