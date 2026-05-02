"""Customer simulation for repeatable demos and stress tests."""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass
from typing import Protocol

from vending.change import ChangeAlgorithm, GreedyChangeAlgorithm
from vending.models import Coin, MachineState, Product, Transaction, TransactionOutcome
from vending.money import Money
from vending.state import cancel_transaction, insert_coin, select_product


@dataclass(frozen=True, slots=True)
class Action:
    kind: str
    value: str | None = None


class Customer(Protocol):
    def choose_product(self, state: MachineState, rng: random.Random) -> Product | None:
        raise NotImplementedError

    def choose_coins(self, product: Product, rng: random.Random) -> list[Coin]:
        raise NotImplementedError


def _available_products(state: MachineState) -> list[Product]:
    return [item.product for item in state.inventory.values() if item.quantity > 0]


def _greedy_unlimited(amount: Money) -> list[Coin]:
    remaining = amount.cents
    coins: list[Coin] = []
    for coin in Coin.ordered_desc():
        while coin.value.cents <= remaining:
            coins.append(coin)
            remaining -= coin.value.cents
    return coins


class RandomCustomer:
    def choose_product(self, state: MachineState, rng: random.Random) -> Product | None:
        products = _available_products(state)
        return rng.choice(products) if products else None

    def choose_coins(self, product: Product, rng: random.Random) -> list[Coin]:
        target = product.price
        if rng.random() < 0.7:
            target = target + rng.choice(
                [Money.zero(), Money("0.25"), Money("0.50"), Money("1.00")]
            )
        return _greedy_unlimited(target)


class BudgetCustomer:
    def choose_product(self, state: MachineState, rng: random.Random) -> Product | None:
        del rng
        products = _available_products(state)
        return min(products, key=lambda product: product.price) if products else None

    def choose_coins(self, product: Product, rng: random.Random) -> list[Coin]:
        del rng
        return _greedy_unlimited(product.price)


class PickyCustomer:
    def __init__(self, categories: tuple[str, ...] = ("candy", "snack")) -> None:
        self.categories = categories

    def choose_product(self, state: MachineState, rng: random.Random) -> Product | None:
        preferred = [
            product for product in _available_products(state) if product.category in self.categories
        ]
        products = preferred or _available_products(state)
        return rng.choice(products) if products else None

    def choose_coins(self, product: Product, rng: random.Random) -> list[Coin]:
        del rng
        return _greedy_unlimited(product.price + Money("0.25"))


class ExactChangeCustomer:
    def choose_product(self, state: MachineState, rng: random.Random) -> Product | None:
        products = _available_products(state)
        return rng.choice(products) if products else None

    def choose_coins(self, product: Product, rng: random.Random) -> list[Coin]:
        del rng
        return _greedy_unlimited(product.price)


CustomerType = (
    type[RandomCustomer]
    | type[BudgetCustomer]
    | type[PickyCustomer]
    | type[ExactChangeCustomer]
)


CUSTOMER_TYPES: tuple[CustomerType, ...] = (
    RandomCustomer,
    BudgetCustomer,
    PickyCustomer,
    ExactChangeCustomer,
)


@dataclass(frozen=True, slots=True)
class SimulationResult:
    state: MachineState
    transactions: tuple[Transaction, ...]
    summary: dict[str, object]


def run_simulation(
    state: MachineState,
    customers: int,
    seed: int | None,
    algorithm: ChangeAlgorithm[Coin] | None = None,
) -> SimulationResult:
    rng = random.Random(seed)
    algorithm = algorithm or GreedyChangeAlgorithm()
    transactions: list[Transaction] = []
    outcomes: Counter[str] = Counter()

    for _ in range(customers):
        customer_type = rng.choice(CUSTOMER_TYPES)
        customer = customer_type()
        product = customer.choose_product(state, rng)
        if product is None:
            outcomes["no_inventory"] += 1
            break
        try:
            for coin in customer.choose_coins(product, rng):
                state = insert_coin(state, coin)
            state, result = select_product(state, product.slot, algorithm)
            outcomes[result.outcome.value] += 1
            if result.transaction:
                transactions.append(result.transaction)
            if result.outcome == TransactionOutcome.INSUFFICIENT_FUNDS:
                state, cancel_result = cancel_transaction(state)
                outcomes[cancel_result.outcome.value] += 1
                if cancel_result.transaction:
                    transactions.append(cancel_result.transaction)
        except Exception as exc:  # Simulation should keep going and count operational failures.
            outcomes[type(exc).__name__] += 1
            if state.current_balance:
                state, cancel_result = cancel_transaction(state)
                if cancel_result.transaction:
                    transactions.append(cancel_result.transaction)

    summary: dict[str, object] = {
        "customers": customers,
        "seed": seed,
        "outcomes": dict(outcomes),
        "successful_transactions": outcomes.get(TransactionOutcome.COMPLETED.value, 0),
        "remaining_inventory": sum(item.quantity for item in state.inventory.values()),
        "cash_total": format(state.cash_total, "plain"),
        "state_transactions": state.stats.transactions,
    }
    return SimulationResult(state=state, transactions=tuple(transactions), summary=summary)
