"""State-driven terminal renderers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from textwrap import shorten

from vending.ansi import ANSI
from vending.change import ChangeAlgorithm
from vending.models import Coin, InventoryItem, MachineState
from vending.state import exact_change_required


class Renderer(ABC):
    @abstractmethod
    def render(self, state: MachineState) -> str:
        raise NotImplementedError


def _stock_text(item: InventoryItem, ansi: ANSI) -> str:
    if item.is_empty:
        return ansi.red("empty")
    if item.is_low:
        return ansi.yellow("low")
    return ansi.green("full")


class ClassicRenderer(Renderer):
    def __init__(
        self, no_color: bool = False, algorithm: ChangeAlgorithm[Coin] | None = None
    ) -> None:
        self.ansi = ANSI(not no_color)
        self.algorithm = algorithm

    def render(self, state: MachineState) -> str:
        rows = []
        for slot, item in sorted(state.inventory.items()):
            name = shorten(item.product.name, width=16, placeholder="..")
            stock = _stock_text(item, self.ansi)
            price = format(item.product.price, "currency")
            exact = (
                self.ansi.dim(" exact")
                if exact_change_required(item.product.price, state.cash_reserves, self.algorithm)
                else ""
            )
            rows.append(
                f"| {slot:<2} | {name:<16} | {price:>7} | "
                f"{item.quantity:>2} {stock:<11}{exact:<6} |"
            )

        width = 62
        border = "+" + "-" * (width - 2) + "+"
        status = [
            f"Mode: {state.mode.value}",
            f"Balance: {state.current_balance:currency}",
            f"Cash float: {state.cash_total:currency}",
            f"Message: {state.last_message}",
        ]
        events = list(state.events[-5:]) or ["No events yet."]
        lines = [border, "| VIRTUAL VENDING MACHINE".ljust(width - 1) + "|", border]
        lines.extend(row[: width - 1].ljust(width - 1) + "|" for row in rows)
        lines.extend([border, "| STATUS".ljust(width - 1) + "|"])
        lines.extend(f"| {line}"[: width - 1].ljust(width - 1) + "|" for line in status)
        lines.extend([border, "| HISTORY".ljust(width - 1) + "|"])
        lines.extend(
            f"| {shorten(event, width=width - 4)}"[: width - 1].ljust(width - 1) + "|"
            for event in events
        )
        lines.append(border)
        return "\n".join(lines)


class CompactRenderer(Renderer):
    def __init__(
        self, no_color: bool = False, algorithm: ChangeAlgorithm[Coin] | None = None
    ) -> None:
        self.ansi = ANSI(not no_color)
        self.algorithm = algorithm

    def render(self, state: MachineState) -> str:
        lines = [
            f"mode={state.mode.value} balance={state.current_balance:currency} "
            f"cash={state.cash_total:currency} message={state.last_message}",
            "slot product          price   qty status exact",
            "---- ---------------- ------- --- ------ -----",
        ]
        for slot, item in sorted(state.inventory.items()):
            exact = (
                "yes"
                if exact_change_required(item.product.price, state.cash_reserves, self.algorithm)
                else "no"
            )
            price = format(item.product.price, "currency")
            lines.append(
                f"{slot:<4} {shorten(item.product.name, width=16, placeholder='..'):<16} "
                f"{price:>7} {item.quantity:>3} "
                f"{_stock_text(item, self.ansi):<6} {exact:<5}"
            )
        return "\n".join(lines)


class MinimalRenderer(Renderer):
    def render(self, state: MachineState) -> str:
        lines = [f"{state.mode.value}|{state.current_balance:plain}|{state.last_message}"]
        for slot, item in sorted(state.inventory.items()):
            lines.append(
                f"{slot}|{item.product.name}|{item.product.price:plain}|{item.quantity}|{item.par_level}"
            )
        return "\n".join(lines)


def get_renderer(
    name: str,
    no_color: bool = False,
    algorithm: ChangeAlgorithm[Coin] | None = None,
) -> Renderer:
    normalized = name.strip().lower()
    if normalized == "classic":
        return ClassicRenderer(no_color=no_color, algorithm=algorithm)
    if normalized == "compact":
        return CompactRenderer(no_color=no_color, algorithm=algorithm)
    if normalized == "minimal":
        return MinimalRenderer()
    raise ValueError(f"unknown renderer: {name!r}")
