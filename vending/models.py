"""Core immutable domain models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from types import MappingProxyType
from typing import TypeVar

from vending.money import Money

K = TypeVar("K")
V = TypeVar("V")


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


class Coin(Enum):
    PENNY = Money("0.01")
    NICKEL = Money("0.05")
    DIME = Money("0.10")
    QUARTER = Money("0.25")
    DOLLAR = Money("1.00")
    FIVE = Money("5.00")
    TEN = Money("10.00")
    TWENTY = Money("20.00")

    @classmethod
    def ordered_desc(cls) -> tuple[Coin, ...]:
        return tuple(sorted(cls, key=lambda coin: coin.value.cents, reverse=True))

    @classmethod
    def from_token(cls, token: str) -> Coin:
        normalized = token.strip().lower()
        aliases = {
            "p": cls.PENNY,
            "penny": cls.PENNY,
            "1c": cls.PENNY,
            "n": cls.NICKEL,
            "nickel": cls.NICKEL,
            "5c": cls.NICKEL,
            "d": cls.DIME,
            "dime": cls.DIME,
            "10c": cls.DIME,
            "q": cls.QUARTER,
            "quarter": cls.QUARTER,
            "25c": cls.QUARTER,
            "$": cls.DOLLAR,
            "$1": cls.DOLLAR,
            "1": cls.DOLLAR,
            "dollar": cls.DOLLAR,
            "one": cls.DOLLAR,
            "$5": cls.FIVE,
            "5": cls.FIVE,
            "five": cls.FIVE,
            "$10": cls.TEN,
            "10": cls.TEN,
            "ten": cls.TEN,
            "$20": cls.TWENTY,
            "20": cls.TWENTY,
            "twenty": cls.TWENTY,
        }
        try:
            return aliases[normalized]
        except KeyError as exc:
            from vending.exceptions import InvalidCoinError

            raise InvalidCoinError(f"unsupported coin or bill: {token!r}") from exc

    def __str__(self) -> str:
        return self.name.lower()


class TransactionOutcome(Enum):
    COMPLETED = "completed"
    INSUFFICIENT_FUNDS = "insufficient_funds"
    OUT_OF_STOCK = "out_of_stock"
    CANCELLED = "cancelled"
    EXACT_CHANGE_REQUIRED = "exact_change_required"
    INVALID_SELECTION = "invalid_selection"
    MACHINE_LOCKED = "machine_locked"


class Mode(Enum):
    NORMAL = "normal"
    SERVICE = "service"
    MAINTENANCE = "maintenance"
    LOCKED = "locked"


@dataclass(frozen=True, slots=True)
class Product:
    slot: str
    name: str
    price: Money
    category: str = "snack"

    def to_dict(self) -> dict[str, str]:
        return {
            "slot": self.slot,
            "name": self.name,
            "price": format(self.price, "plain"),
            "category": self.category,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> Product:
        return cls(
            slot=str(data["slot"]).upper(),
            name=str(data["name"]),
            price=Money(str(data["price"])),
            category=str(data.get("category", "snack")),
        )


@dataclass(frozen=True, slots=True)
class InventoryItem:
    product: Product
    quantity: int
    par_level: int

    @property
    def is_empty(self) -> bool:
        return self.quantity <= 0

    @property
    def is_low(self) -> bool:
        return 0 < self.quantity <= self.par_level

    def to_dict(self) -> dict[str, object]:
        return {
            "product": self.product.to_dict(),
            "quantity": self.quantity,
            "par_level": self.par_level,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> InventoryItem:
        product_data = data["product"]
        if not isinstance(product_data, Mapping):
            raise TypeError("inventory product must be a mapping")
        return cls(
            product=Product.from_dict(product_data),
            quantity=int(str(data["quantity"])),
            par_level=int(str(data.get("par_level", 5))),
        )


@dataclass(frozen=True, slots=True)
class MachineStats:
    started_at: str = field(default_factory=utc_now)
    transactions: int = 0
    successful: int = 0
    failed: int = 0
    revenue: Money = field(default_factory=Money.zero)

    def to_dict(self) -> dict[str, object]:
        return {
            "started_at": self.started_at,
            "transactions": self.transactions,
            "successful": self.successful,
            "failed": self.failed,
            "revenue": format(self.revenue, "plain"),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> MachineStats:
        return cls(
            started_at=str(data.get("started_at", utc_now())),
            transactions=int(str(data.get("transactions", 0))),
            successful=int(str(data.get("successful", 0))),
            failed=int(str(data.get("failed", 0))),
            revenue=Money(str(data.get("revenue", "0.00"))),
        )


def _freeze_mapping(mapping: Mapping[K, V]) -> Mapping[K, V]:
    return MappingProxyType(dict(mapping))


@dataclass(frozen=True)
class MachineState:
    inventory: Mapping[str, InventoryItem]
    cash_reserves: Mapping[Coin, int]
    pending_inserted: Mapping[Coin, int] = field(default_factory=dict)
    current_balance: Money = field(default_factory=Money.zero)
    mode: Mode = Mode.NORMAL
    stats: MachineStats = field(default_factory=MachineStats)
    last_message: str = "Select an item."
    events: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "inventory", _freeze_mapping(self.inventory))
        object.__setattr__(self, "cash_reserves", _freeze_mapping(self.cash_reserves))
        object.__setattr__(self, "pending_inserted", _freeze_mapping(self.pending_inserted))
        object.__setattr__(self, "current_balance", Money(self.current_balance))
        object.__setattr__(self, "events", tuple(self.events))

    @property
    def cash_total(self) -> Money:
        total = Money.zero()
        for coin, count in self.cash_reserves.items():
            total += coin.value * count
        return total

    @property
    def pending_total(self) -> Money:
        total = Money.zero()
        for coin, count in self.pending_inserted.items():
            total += coin.value * count
        return total


@dataclass(frozen=True, slots=True)
class Transaction:
    started_at: str
    coins_inserted: Mapping[Coin, int]
    slot_selected: str | None
    outcome: TransactionOutcome
    change_returned: Mapping[Coin, int]
    completed_at: str
    message: str
    paid: Money = field(default_factory=Money.zero)
    price: Money = field(default_factory=Money.zero)
    product_name: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "started_at": self.started_at,
            "coins_inserted": {coin.name: count for coin, count in self.coins_inserted.items()},
            "slot_selected": self.slot_selected,
            "outcome": self.outcome.value,
            "change_returned": {coin.name: count for coin, count in self.change_returned.items()},
            "completed_at": self.completed_at,
            "message": self.message,
            "paid": format(self.paid, "plain"),
            "price": format(self.price, "plain"),
            "product_name": self.product_name,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> Transaction:
        inserted_data = data.get("coins_inserted", {})
        change_data = data.get("change_returned", {})
        if not isinstance(inserted_data, Mapping):
            inserted_data = {}
        if not isinstance(change_data, Mapping):
            change_data = {}
        inserted = {
            Coin[str(coin_name)]: int(str(count))
            for coin_name, count in inserted_data.items()
        }
        change = {
            Coin[str(coin_name)]: int(str(count))
            for coin_name, count in change_data.items()
        }
        return cls(
            started_at=str(data["started_at"]),
            coins_inserted=inserted,
            slot_selected=(
                None if data.get("slot_selected") is None else str(data.get("slot_selected"))
            ),
            outcome=TransactionOutcome(str(data["outcome"])),
            change_returned=change,
            completed_at=str(data["completed_at"]),
            message=str(data.get("message", "")),
            paid=Money(str(data.get("paid", "0.00"))),
            price=Money(str(data.get("price", "0.00"))),
            product_name=(
                None if data.get("product_name") is None else str(data.get("product_name"))
            ),
        )


@dataclass(frozen=True, slots=True)
class TransactionResult:
    outcome: TransactionOutcome
    message: str
    product: Product | None = None
    paid: Money = field(default_factory=Money.zero)
    price: Money = field(default_factory=Money.zero)
    change: Mapping[Coin, int] = field(default_factory=dict)
    transaction: Transaction | None = None
