"""Test change algorithms."""

from dataclasses import dataclass

from vending.change import GreedyChangeAlgorithm, OptimalChangeAlgorithm
from vending.models import Coin
from vending.money import Money


@dataclass(frozen=True)
class Denomination:
    name: str
    value: Money


def test_greedy_and_optimal_agree_for_us_currency() -> None:
    reserves = {coin: 10 for coin in Coin}
    amount = Money("3.85")
    greedy = GreedyChangeAlgorithm().make_change(amount, reserves)
    optimal = OptimalChangeAlgorithm().make_change(amount, reserves)
    assert greedy == optimal


def test_change_returns_none_when_reserves_cannot_make_amount() -> None:
    reserves = {Coin.QUARTER: 1, Coin.DIME: 0, Coin.NICKEL: 0, Coin.PENNY: 0}
    assert GreedyChangeAlgorithm().make_change(Money("0.30"), reserves) is None
    assert OptimalChangeAlgorithm().make_change(Money("0.30"), reserves) is None


def test_optimal_beats_greedy_for_non_canonical_denominations() -> None:
    one = Denomination("one", Money.from_cents(1))
    three = Denomination("three", Money.from_cents(3))
    four = Denomination("four", Money.from_cents(4))
    reserves = {one: 10, three: 10, four: 10}

    greedy = GreedyChangeAlgorithm().make_change(Money.from_cents(6), reserves)
    optimal = OptimalChangeAlgorithm().make_change(Money.from_cents(6), reserves)

    assert greedy == {four: 1, one: 2}
    assert optimal == {three: 2}
