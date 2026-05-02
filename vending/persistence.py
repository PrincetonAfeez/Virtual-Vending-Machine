"""Persistence helpers for config, state, catalog, and inventory."""

from __future__ import annotations

import json
import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, cast

from vending.models import Coin, InventoryItem, MachineState, MachineStats
from vending.money import Money
from vending.state import build_initial_state, hash_pin

APP_DIR = Path.home() / ".vending"


@dataclass(frozen=True, slots=True)
class Config:
    config_path: Path
    data_dir: Path
    currency: str
    algorithm: str
    renderer: str
    max_balance: Money
    service_pin_hash: str
    starting_float: Mapping[Coin, int]
    state_file: Path
    products_file: Path
    inventory_file: Path
    transactions_file: Path


def _resource_text(name: str) -> str:
    return resources.files("vending.data").joinpath(name).read_text(encoding="utf-8")


def default_products_data() -> list[dict[str, Any]]:
    data = json.loads(_resource_text("default_products.json"))
    if not isinstance(data, list):
        raise ValueError("default products must be a list")
    return cast(list[dict[str, Any]], data)


def default_config_text() -> str:
    text = _resource_text("default_config.toml")
    return text.replace('service_pin_hash = ""', f'service_pin_hash = "{hash_pin("1234")}"')


def _resolve_path(raw: str | os.PathLike[str], data_dir: Path) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = data_dir / path
    return path


def load_config(config_path: str | os.PathLike[str] | None = None) -> Config:
    path = Path(config_path).expanduser() if config_path else APP_DIR / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(default_config_text(), encoding="utf-8")

    data = tomllib.loads(path.read_text(encoding="utf-8"))
    data_dir = path.parent
    starting_float = {
        Coin[name]: int(count) for name, count in dict(data.get("starting_float", {})).items()
    }
    service_pin_hash = str(data.get("service_pin_hash") or hash_pin("1234"))

    config = Config(
        config_path=path,
        data_dir=data_dir,
        currency=str(data.get("currency", "USD")),
        algorithm=str(data.get("algorithm", "optimal")),
        renderer=str(data.get("renderer", "classic")),
        max_balance=Money(str(data.get("max_balance", "20.00"))),
        service_pin_hash=service_pin_hash,
        starting_float=starting_float,
        state_file=_resolve_path(str(data.get("state_file", "state.json")), data_dir),
        products_file=_resolve_path(str(data.get("products_file", "products.json")), data_dir),
        inventory_file=_resolve_path(str(data.get("inventory_file", "inventory.json")), data_dir),
        transactions_file=_resolve_path(
            str(data.get("transactions_file", "transactions.jsonl")), data_dir
        ),
    )
    ensure_defaults(config)
    return config


def ensure_defaults(config: Config) -> None:
    config.data_dir.mkdir(parents=True, exist_ok=True)
    if not config.products_file.exists():
        config.products_file.write_text(
            json.dumps(default_products_data(), indent=2) + "\n", encoding="utf-8"
        )
    if not config.inventory_file.exists():
        inventory_rows = [
            {
                "slot": row["slot"],
                "quantity": row.get("quantity", 0),
                "par_level": row.get("par_level", 5),
            }
            for row in default_products_data()
        ]
        config.inventory_file.write_text(
            json.dumps(inventory_rows, indent=2) + "\n", encoding="utf-8"
        )
    config.transactions_file.parent.mkdir(parents=True, exist_ok=True)
    if not config.transactions_file.exists():
        config.transactions_file.touch()


def load_products(path: Path) -> dict[str, InventoryItem]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    inventory: dict[str, InventoryItem] = {}
    for row in rows:
        item = InventoryItem.from_dict(
            {
                "product": row,
                "quantity": int(row.get("quantity", 0)),
                "par_level": int(row.get("par_level", 5)),
            }
        )
        inventory[item.product.slot] = item
    return inventory


def load_inventory(products_file: Path, inventory_file: Path) -> dict[str, InventoryItem]:
    products = load_products(products_file)
    if not inventory_file.exists():
        return products
    rows = json.loads(inventory_file.read_text(encoding="utf-8"))
    for row in rows:
        slot = str(row["slot"]).upper()
        if slot not in products:
            continue
        item = products[slot]
        products[slot] = InventoryItem(
            product=item.product,
            quantity=int(row.get("quantity", item.quantity)),
            par_level=int(row.get("par_level", item.par_level)),
        )
    return products


def state_to_dict(state: MachineState) -> dict[str, Any]:
    return {
        "inventory": {slot: item.to_dict() for slot, item in state.inventory.items()},
        "cash_reserves": {coin.name: count for coin, count in state.cash_reserves.items()},
        "pending_inserted": {coin.name: count for coin, count in state.pending_inserted.items()},
        "current_balance": format(state.current_balance, "plain"),
        "mode": state.mode.value,
        "stats": state.stats.to_dict(),
        "last_message": state.last_message,
        "events": list(state.events),
    }


def state_from_dict(data: Mapping[str, Any]) -> MachineState:
    from vending.models import Mode

    inventory = {
        str(slot).upper(): InventoryItem.from_dict(item)
        for slot, item in dict(data["inventory"]).items()
    }
    cash_reserves = {
        Coin[str(coin_name)]: int(count)
        for coin_name, count in dict(data.get("cash_reserves", {})).items()
    }
    pending = {
        Coin[str(coin_name)]: int(count)
        for coin_name, count in dict(data.get("pending_inserted", {})).items()
    }
    return MachineState(
        inventory=inventory,
        cash_reserves=cash_reserves,
        pending_inserted=pending,
        current_balance=Money(str(data.get("current_balance", "0.00"))),
        mode=Mode(str(data.get("mode", "normal"))),
        stats=MachineStats.from_dict(data.get("stats", {})),
        last_message=str(data.get("last_message", "Select an item.")),
        events=tuple(str(event) for event in data.get("events", ())),
    )


def load_state(config: Config, state_file: Path | None = None) -> MachineState:
    path = state_file or config.state_file
    if path.exists():
        return state_from_dict(json.loads(path.read_text(encoding="utf-8")))
    inventory = load_inventory(config.products_file, config.inventory_file)
    return build_initial_state(inventory, config.starting_float)


def save_state_atomic(state: MachineState, state_file: Path) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    temp_path = state_file.with_suffix(state_file.suffix + ".tmp")
    temp_path.write_text(json.dumps(state_to_dict(state), indent=2) + "\n", encoding="utf-8")
    os.replace(temp_path, state_file)


def reset_factory(config: Config) -> None:
    for path in (
        config.state_file,
        config.products_file,
        config.inventory_file,
        config.transactions_file,
    ):
        if path.exists():
            path.unlink()
    ensure_defaults(config)
