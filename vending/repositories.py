"""Repository abstractions and JSON-backed implementations."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import date
from pathlib import Path

from vending.exceptions import InvalidSlotError
from vending.models import InventoryItem, Transaction
from vending.persistence import load_inventory


class InventoryRepository(ABC):
    @abstractmethod
    def load(self) -> dict[str, InventoryItem]:
        raise NotImplementedError

    @abstractmethod
    def save(self, inventory: Mapping[str, InventoryItem]) -> None:
        raise NotImplementedError

    def adjust(self, slot: str, delta: int) -> dict[str, InventoryItem]:
        inventory = self.load()
        normalized = slot.upper()
        if normalized not in inventory:
            raise InvalidSlotError(f"slot {normalized} does not exist")
        item = inventory[normalized]
        inventory[normalized] = replace(item, quantity=max(0, item.quantity + delta))
        self.save(inventory)
        return inventory

    def restock(self, slot: str, quantity: int) -> dict[str, InventoryItem]:
        return self.adjust(slot, quantity)

    def set_par(self, slot: str, level: int) -> dict[str, InventoryItem]:
        inventory = self.load()
        normalized = slot.upper()
        if normalized not in inventory:
            raise InvalidSlotError(f"slot {normalized} does not exist")
        inventory[normalized] = replace(inventory[normalized], par_level=level)
        self.save(inventory)
        return inventory


class JsonInventoryRepository(InventoryRepository):
    def __init__(self, products_file: Path, inventory_file: Path) -> None:
        self.products_file = products_file
        self.inventory_file = inventory_file

    def load(self) -> dict[str, InventoryItem]:
        return load_inventory(self.products_file, self.inventory_file)

    def save(self, inventory: Mapping[str, InventoryItem]) -> None:
        rows = [
            {"slot": slot, "quantity": item.quantity, "par_level": item.par_level}
            for slot, item in sorted(inventory.items())
        ]
        self.inventory_file.parent.mkdir(parents=True, exist_ok=True)
        self.inventory_file.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")


class InMemoryInventoryRepository(InventoryRepository):
    def __init__(self, inventory: Mapping[str, InventoryItem]) -> None:
        self._inventory = dict(inventory)

    def load(self) -> dict[str, InventoryItem]:
        return dict(self._inventory)

    def save(self, inventory: Mapping[str, InventoryItem]) -> None:
        self._inventory = dict(inventory)


class TransactionRepository(ABC):
    @abstractmethod
    def append(self, transaction: Transaction) -> None:
        raise NotImplementedError

    @abstractmethod
    def all(self) -> list[Transaction]:
        raise NotImplementedError

    def query_by_date(self, target: date) -> list[Transaction]:
        prefix = target.isoformat()
        return [tx for tx in self.all() if tx.completed_at.startswith(prefix)]

    def query_by_slot(self, slot: str) -> list[Transaction]:
        normalized = slot.upper()
        return [tx for tx in self.all() if tx.slot_selected == normalized]

    def aggregate(self) -> dict[str, object]:
        transactions = self.all()
        return {
            "count": len(transactions),
            "completed": sum(1 for tx in transactions if tx.outcome.value == "completed"),
            "failed": sum(1 for tx in transactions if tx.outcome.value != "completed"),
        }


class JsonlTransactionRepository(TransactionRepository):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    def append(self, transaction: Transaction) -> None:
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(transaction.to_dict(), sort_keys=True) + "\n")

    def all(self) -> list[Transaction]:
        transactions: list[Transaction] = []
        if not self.path.exists():
            return transactions
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                transactions.append(Transaction.from_dict(json.loads(line)))
        return transactions


class InMemoryTransactionRepository(TransactionRepository):
    def __init__(self, transactions: Iterable[Transaction] = ()) -> None:
        self._transactions = list(transactions)

    def append(self, transaction: Transaction) -> None:
        self._transactions.append(transaction)

    def all(self) -> list[Transaction]:
        return list(self._transactions)

