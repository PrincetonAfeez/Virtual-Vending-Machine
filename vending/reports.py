"""Reporting helpers for operator and CLI views."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from decimal import Decimal
from io import StringIO
from typing import Any

from vending.models import Coin, InventoryItem, MachineState, Transaction, TransactionOutcome
from vending.money import Money


def _money_total(values: Iterable[Money]) -> Money:
    total = Money.zero()
    for value in values:
        total += value
    return total


def sales_report(
    transactions: Iterable[Transaction], group_by: str | None = None
) -> dict[str, Any]:
    txs = list(transactions)
    completed = [tx for tx in txs if tx.outcome == TransactionOutcome.COMPLETED]
    revenue = _money_total(tx.price for tx in completed)
    average = revenue * (Decimal(1) / Decimal(len(completed))) if completed else Money.zero()
    report: dict[str, Any] = {
        "transaction_count": len(txs),
        "completed_count": len(completed),
        "failed_count": len(txs) - len(completed),
        "revenue": format(revenue, "plain"),
        "average_transaction": format(average, "plain"),
    }
    if group_by:
        groups: defaultdict[str, Money] = defaultdict(Money.zero)
        counts: Counter[str] = Counter()
        for tx in completed:
            if group_by == "day":
                key = tx.completed_at[:10]
            elif group_by == "hour":
                key = tx.completed_at[:13]
            elif group_by == "slot":
                key = tx.slot_selected or "unknown"
            else:
                key = "all"
            groups[key] = groups[key] + tx.price
            counts[key] += 1
        report[f"by_{group_by}"] = {
            key: {"count": counts[key], "revenue": format(value, "plain")}
            for key, value in sorted(groups.items())
        }
    return report


def inventory_report(inventory: Mapping[str, InventoryItem]) -> dict[str, Any]:
    rows = []
    below_par = []
    for slot, item in sorted(inventory.items()):
        row = {
            "slot": slot,
            "name": item.product.name,
            "category": item.product.category,
            "price": format(item.product.price, "plain"),
            "quantity": item.quantity,
            "par_level": item.par_level,
            "below_par": item.quantity < item.par_level,
        }
        rows.append(row)
        if row["below_par"]:
            below_par.append(row)
    return {"items": rows, "below_par": below_par}


def cash_report(state: MachineState) -> dict[str, Any]:
    rows = []
    for coin in Coin.ordered_desc():
        count = int(state.cash_reserves.get(coin, 0))
        rows.append(
            {
                "denomination": coin.name,
                "value": format(coin.value, "plain"),
                "count": count,
                "total": format(coin.value * count, "plain"),
            }
        )
    return {"total": format(state.cash_total, "plain"), "reserves": rows}


def top_sellers_report(transactions: Iterable[Transaction], limit: int = 10) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    revenue: defaultdict[str, Money] = defaultdict(Money.zero)
    for tx in transactions:
        if tx.outcome != TransactionOutcome.COMPLETED:
            continue
        key = tx.product_name or tx.slot_selected or "unknown"
        counts[key] += 1
        revenue[key] = revenue[key] + tx.price
    rows = [
        {"product": name, "count": count, "revenue": format(revenue[name], "plain")}
        for name, count in counts.most_common(limit)
    ]
    return {"top_sellers": rows}


def failed_report(transactions: Iterable[Transaction]) -> dict[str, Any]:
    rows = [tx.to_dict() for tx in transactions if tx.outcome != TransactionOutcome.COMPLETED]
    counts = Counter(str(row["outcome"]) for row in rows)
    return {"failed_count": len(rows), "by_outcome": dict(counts), "transactions": rows}


def audit_report(state: MachineState) -> dict[str, Any]:
    issues: list[str] = []
    if state.current_balance != state.pending_total:
        issues.append("current balance does not match pending inserted money")
    for slot, item in state.inventory.items():
        if item.quantity < 0:
            issues.append(f"{slot} has negative inventory")
    for coin, count in state.cash_reserves.items():
        if count < 0:
            issues.append(f"{coin.name} has negative cash reserve")
    return {
        "ok": not issues,
        "issues": issues,
        "cash_total": format(state.cash_total, "plain"),
        "pending_total": format(state.pending_total, "plain"),
        "transactions_recorded_in_state": state.stats.transactions,
    }


def format_report(report: dict[str, Any], output_format: str = "plain") -> str:
    normalized = output_format.lower()
    if normalized == "json":
        return json.dumps(report, indent=2)
    if normalized == "csv":
        return _format_csv(report)
    return _format_plain(report)


def _format_plain(value: Any, indent: int = 0) -> str:
    pad = " " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{pad}{key}:")
                lines.append(_format_plain(item, indent + 2))
            else:
                lines.append(f"{pad}{key}: {item}")
        return "\n".join(lines)
    if isinstance(value, list):
        if not value:
            return f"{pad}(none)"
        return "\n".join(f"{pad}- {_format_inline(item)}" for item in value)
    return f"{pad}{value}"


def _format_inline(value: Any) -> str:
    if isinstance(value, dict):
        return ", ".join(f"{key}={item}" for key, item in value.items())
    return str(value)


def _format_csv(report: dict[str, Any]) -> str:
    rows: list[dict[str, Any]]
    for value in report.values():
        if isinstance(value, list) and all(isinstance(row, dict) for row in value):
            rows = value
            break
        if isinstance(value, dict):
            nested = list(value.values())
            if nested and all(isinstance(row, dict) for row in nested):
                rows = [{"key": key, **row} for key, row in value.items()]
                break
    else:
        rows = [report]
    if not rows:
        return ""
    output = StringIO()
    fieldnames = sorted({key for row in rows for key in row})
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().strip()
