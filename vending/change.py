"""Change-making strategies."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Protocol, TypeVar

from vending.models import Coin
from vending.money import Money

Denomination = TypeVar("Denomination")


class ChangeAlgorithm(Protocol[Denomination]):
    def make_change(
        self, amount: Money, reserves: Mapping[Denomination, int]
    ) -> dict[Denomination, int] | None:
        """Return a denomination count or ``None`` when change is impossible."""


def denomination_value(denomination: object) -> Money:
    value = getattr(denomination, "value", denomination)
    if isinstance(value, Money):
        return value
    return Money.from_cents(int(str(value)))


class GreedyChangeAlgorithm:
    """Largest-denomination-first change.

    This is fast and works for canonical US currency, but it is not optimal for
    every possible denomination system.
    """

    def make_change(
        self, amount: Money, reserves: Mapping[Denomination, int]
    ) -> dict[Denomination, int] | None:
        remaining = amount.cents
        if remaining < 0:
            return None
        if remaining == 0:
            return {}

        result: dict[Denomination, int] = {}
        ordered = sorted(reserves, key=lambda denom: denomination_value(denom).cents, reverse=True)
        for denomination in ordered:
            value = denomination_value(denomination).cents
            if value <= 0:
                continue
            use = min(int(reserves[denomination]), remaining // value)
            if use:
                result[denomination] = use
                remaining -= use * value
            if remaining == 0:
                return result
        return None


class OptimalChangeAlgorithm:
    """Bounded dynamic-programming change with the fewest pieces."""

    def make_change(
        self, amount: Money, reserves: Mapping[Denomination, int]
    ) -> dict[Denomination, int] | None:
        target = amount.cents
        if target < 0:
            return None
        if target == 0:
            return {}

        dp: list[list[Denomination] | None] = [None] * (target + 1)
        dp[0] = []
        ordered = sorted(reserves, key=lambda denom: denomination_value(denom).cents, reverse=True)

        for denomination in ordered:
            value = denomination_value(denomination).cents
            if value <= 0:
                continue
            for _ in range(max(0, int(reserves[denomination]))):
                for cents in range(target, value - 1, -1):
                    previous = dp[cents - value]
                    if previous is None:
                        continue
                    candidate = [*previous, denomination]
                    if dp[cents] is None or len(candidate) < len(dp[cents]):  # type: ignore[arg-type]
                        dp[cents] = candidate

        if dp[target] is None:
            return None
        return dict(Counter(dp[target]))


def get_change_algorithm(name: str) -> ChangeAlgorithm[Coin]:
    normalized = name.strip().lower()
    if normalized == "greedy":
        return GreedyChangeAlgorithm()
    if normalized == "optimal":
        return OptimalChangeAlgorithm()
    raise ValueError(f"unknown change algorithm: {name!r}")
