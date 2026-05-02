"""Pure state transitions for the vending machine."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import replace

from vending.change import ChangeAlgorithm, GreedyChangeAlgorithm
from vending.exceptions import (
    AccessDeniedError,
    InvalidCoinError,
    InvalidSlotError,
    ServiceModeRequiredError,
)
from vending.models import (
    Coin,
    InventoryItem,
    MachineState,
    MachineStats,
    Mode,
    Product,
    Transaction,
    TransactionOutcome,
    TransactionResult,
    utc_now,
)
from vending.money import Money

SLOT_PATTERN = re.compile(r"^[A-H][1-9]$")
DEFAULT_MAX_BALANCE = Money("20.00")
DEFAULT_KEEP_FLOAT = Money("20.00")


def hash_pin(pin: str) -> str:
    return hashlib.sha256(pin.encode("utf-8")).hexdigest()


def normalize_slot(slot: str) -> str:
    return slot.strip().upper()


def validate_slot_code(slot: str) -> str:
    normalized = normalize_slot(slot)
    if not SLOT_PATTERN.fullmatch(normalized):
        raise InvalidSlotError("slot codes must look like A1 through H9")
    return normalized


def build_initial_state(
    inventory: Mapping[str, InventoryItem],
    starting_reserves: Mapping[Coin, int] | None = None,
) -> MachineState:
    reserves = {coin: int((starting_reserves or {}).get(coin, 0)) for coin in Coin}
    normalized_inventory = {normalize_slot(slot): item for slot, item in inventory.items()}
    return MachineState(
        inventory=normalized_inventory,
        cash_reserves=reserves,
        last_message="Select an item.",
        events=("Machine initialized.",),
    )


def _add_event(state: MachineState, message: str, **changes: object) -> MachineState:
    event = f"{utc_now()} {message}"
    events = (*state.events, event)[-5:]
    return replace(state, last_message=message, events=events, **changes)  # type: ignore[arg-type]


def _copy_counts(counts: Mapping[Coin, int]) -> dict[Coin, int]:
    return {coin: int(counts.get(coin, 0)) for coin in Coin}


def _add_counts(left: Mapping[Coin, int], right: Mapping[Coin, int]) -> dict[Coin, int]:
    result = _copy_counts(left)
    for coin, count in right.items():
        result[coin] = result.get(coin, 0) + int(count)
    return {coin: count for coin, count in result.items() if count}


def _subtract_counts(left: Mapping[Coin, int], right: Mapping[Coin, int]) -> dict[Coin, int]:
    result = _copy_counts(left)
    for coin, count in right.items():
        result[coin] = result.get(coin, 0) - int(count)
        if result[coin] < 0:
            raise ValueError(f"negative cash reserve for {coin.name}")
    return {coin: count for coin, count in result.items() if count}


def _update_stats(
    stats: MachineStats, outcome: TransactionOutcome, price: Money | None = None
) -> MachineStats:
    price = price or Money.zero()
    success = outcome == TransactionOutcome.COMPLETED
    return replace(
        stats,
        transactions=stats.transactions + 1,
        successful=stats.successful + (1 if success else 0),
        failed=stats.failed + (0 if success else 1),
        revenue=stats.revenue + (price if success else Money.zero()),
    )


def _transaction(
    state: MachineState,
    outcome: TransactionOutcome,
    message: str,
    slot: str | None = None,
    product: Product | None = None,
    change: Mapping[Coin, int] | None = None,
) -> Transaction:
    return Transaction(
        started_at=utc_now(),
        coins_inserted=dict(state.pending_inserted),
        slot_selected=slot,
        outcome=outcome,
        change_returned=dict(change or {}),
        completed_at=utc_now(),
        message=message,
        paid=state.current_balance,
        price=product.price if product else Money.zero(),
        product_name=product.name if product else None,
    )


def insert_coin(
    state: MachineState, coin: Coin | str, max_balance: Money | None = None
) -> MachineState:
    max_balance = max_balance or DEFAULT_MAX_BALANCE
    if state.mode != Mode.NORMAL:
        raise AccessDeniedError(f"cannot insert money while machine is in {state.mode.value} mode")
    if isinstance(coin, str):
        coin = Coin.from_token(coin)
    if not isinstance(coin, Coin):
        raise InvalidCoinError("unsupported coin or bill")

    new_balance = state.current_balance + coin.value
    if new_balance > max_balance:
        raise InvalidCoinError(f"maximum balance is {max_balance:currency}")
    pending = _copy_counts(state.pending_inserted)
    pending[coin] = pending.get(coin, 0) + 1
    return _add_event(
        state,
        f"Inserted {coin.value:currency}. Balance: {new_balance:currency}.",
        current_balance=new_balance,
        pending_inserted={coin: count for coin, count in pending.items() if count},
    )


def select_product(
    state: MachineState,
    slot: str,
    algorithm: ChangeAlgorithm[Coin] | None = None,
) -> tuple[MachineState, TransactionResult]:
    algorithm = algorithm or GreedyChangeAlgorithm()
    if state.mode != Mode.NORMAL:
        message = "Machine is locked for customer purchases."
        result = TransactionResult(TransactionOutcome.MACHINE_LOCKED, message)
        return _add_event(state, message), result

    try:
        normalized = validate_slot_code(slot)
    except InvalidSlotError:
        message = f"Invalid selection: {slot!r}."
        tx = _transaction(state, TransactionOutcome.INVALID_SELECTION, message, slot=slot)
        new_state = _add_event(
            state,
            message,
            stats=_update_stats(state.stats, TransactionOutcome.INVALID_SELECTION),
        )
        return new_state, TransactionResult(
            TransactionOutcome.INVALID_SELECTION,
            message,
            paid=state.current_balance,
            transaction=tx,
        )

    item = state.inventory.get(normalized)
    if item is None:
        message = f"Slot {normalized} is empty."
        tx = _transaction(state, TransactionOutcome.INVALID_SELECTION, message, slot=normalized)
        new_state = _add_event(
            state,
            message,
            stats=_update_stats(state.stats, TransactionOutcome.INVALID_SELECTION),
        )
        return new_state, TransactionResult(
            TransactionOutcome.INVALID_SELECTION,
            message,
            paid=state.current_balance,
            transaction=tx,
        )

    product = item.product
    if item.quantity <= 0:
        message = f"{product.name} is out of stock."
        tx = _transaction(
            state, TransactionOutcome.OUT_OF_STOCK, message, slot=normalized, product=product
        )
        new_state = _add_event(
            state,
            message,
            stats=_update_stats(state.stats, TransactionOutcome.OUT_OF_STOCK),
        )
        return new_state, TransactionResult(
            TransactionOutcome.OUT_OF_STOCK,
            message,
            product=product,
            paid=state.current_balance,
            price=product.price,
            transaction=tx,
        )

    if state.current_balance < product.price:
        short = product.price - state.current_balance
        message = f"Insert {short:currency} more for {product.name}."
        return _add_event(state, message), TransactionResult(
            TransactionOutcome.INSUFFICIENT_FUNDS,
            message,
            product=product,
            paid=state.current_balance,
            price=product.price,
        )

    change_due = state.current_balance - product.price
    change = algorithm.make_change(change_due, state.cash_reserves)
    if change is None:
        message = "Exact change required. Refunding inserted money."
        refund = dict(state.pending_inserted)
        tx = _transaction(
            state,
            TransactionOutcome.EXACT_CHANGE_REQUIRED,
            message,
            slot=normalized,
            product=product,
            change=refund,
        )
        new_state = _add_event(
            state,
            message,
            pending_inserted={},
            current_balance=Money.zero(),
            stats=_update_stats(state.stats, TransactionOutcome.EXACT_CHANGE_REQUIRED),
        )
        return new_state, TransactionResult(
            TransactionOutcome.EXACT_CHANGE_REQUIRED,
            message,
            product=product,
            paid=state.current_balance,
            price=product.price,
            change=refund,
            transaction=tx,
        )

    inventory = dict(state.inventory)
    inventory[normalized] = replace(item, quantity=item.quantity - 1)
    reserves = _subtract_counts(_add_counts(state.cash_reserves, state.pending_inserted), change)
    message = f"Dispensed {product.name}. Change: {format_change(change)}."
    tx = _transaction(
        state,
        TransactionOutcome.COMPLETED,
        message,
        slot=normalized,
        product=product,
        change=change,
    )
    new_state = _add_event(
        state,
        message,
        inventory=inventory,
        cash_reserves=reserves,
        pending_inserted={},
        current_balance=Money.zero(),
        stats=_update_stats(state.stats, TransactionOutcome.COMPLETED, product.price),
    )
    return new_state, TransactionResult(
        TransactionOutcome.COMPLETED,
        message,
        product=product,
        paid=state.current_balance,
        price=product.price,
        change=change,
        transaction=tx,
    )


def cancel_transaction(state: MachineState) -> tuple[MachineState, TransactionResult]:
    if not state.current_balance:
        message = "No balance to refund."
        return _add_event(state, message), TransactionResult(TransactionOutcome.CANCELLED, message)

    refund = dict(state.pending_inserted)
    message = f"Transaction cancelled. Refunded {state.current_balance:currency}."
    tx = _transaction(state, TransactionOutcome.CANCELLED, message, change=refund)
    new_state = _add_event(
        state,
        message,
        pending_inserted={},
        current_balance=Money.zero(),
        stats=_update_stats(state.stats, TransactionOutcome.CANCELLED),
    )
    return new_state, TransactionResult(
        TransactionOutcome.CANCELLED,
        message,
        paid=state.current_balance,
        change=refund,
        transaction=tx,
    )


def enter_service_mode(state: MachineState, pin: str, expected_pin_hash: str) -> MachineState:
    if hash_pin(pin) != expected_pin_hash:
        raise AccessDeniedError("incorrect service PIN")
    return _add_event(state, "Service mode enabled.", mode=Mode.SERVICE)


def exit_service_mode(state: MachineState) -> MachineState:
    return _add_event(state, "Returned to normal mode.", mode=Mode.NORMAL)


def require_service(state: MachineState) -> None:
    if state.mode != Mode.SERVICE:
        raise ServiceModeRequiredError("service mode required")


def lock_machine(state: MachineState) -> MachineState:
    require_service(state)
    return _add_event(state, "Machine locked.", mode=Mode.LOCKED)


def unlock_machine(state: MachineState, pin: str, expected_pin_hash: str) -> MachineState:
    if hash_pin(pin) != expected_pin_hash:
        raise AccessDeniedError("incorrect service PIN")
    return _add_event(state, "Machine unlocked.", mode=Mode.NORMAL)


def restock_slot(state: MachineState, slot: str, quantity: int) -> MachineState:
    require_service(state)
    normalized = validate_slot_code(slot)
    if quantity < 0:
        raise ValueError("quantity must be non-negative")
    item = state.inventory.get(normalized)
    if item is None:
        raise InvalidSlotError(f"slot {normalized} does not exist")
    inventory = dict(state.inventory)
    inventory[normalized] = replace(item, quantity=item.quantity + quantity)
    return _add_event(state, f"Restocked {normalized} by {quantity}.", inventory=inventory)


def restock_all_to_par(state: MachineState) -> MachineState:
    require_service(state)
    inventory: dict[str, InventoryItem] = {}
    changed = 0
    for slot, item in state.inventory.items():
        target = max(item.quantity, item.par_level)
        if target != item.quantity:
            changed += target - item.quantity
        inventory[slot] = replace(item, quantity=target)
    return _add_event(state, f"Restocked all low slots by {changed} units.", inventory=inventory)


def set_par_level(state: MachineState, slot: str, par_level: int) -> MachineState:
    require_service(state)
    normalized = validate_slot_code(slot)
    if par_level < 0:
        raise ValueError("par level must be non-negative")
    item = state.inventory.get(normalized)
    if item is None:
        raise InvalidSlotError(f"slot {normalized} does not exist")
    inventory = dict(state.inventory)
    inventory[normalized] = replace(item, par_level=par_level)
    return _add_event(state, f"Set {normalized} par level to {par_level}.", inventory=inventory)


def set_price(state: MachineState, slot: str, price: Money) -> MachineState:
    require_service(state)
    normalized = validate_slot_code(slot)
    item = state.inventory.get(normalized)
    if item is None:
        raise InvalidSlotError(f"slot {normalized} does not exist")
    product = replace(item.product, price=Money(price))
    inventory = dict(state.inventory)
    inventory[normalized] = replace(item, product=product)
    return _add_event(state, f"Set {normalized} price to {price:currency}.", inventory=inventory)


def add_product(
    state: MachineState,
    slot: str,
    name: str,
    price: Money,
    category: str,
    quantity: int,
    par_level: int,
) -> MachineState:
    require_service(state)
    normalized = validate_slot_code(slot)
    product = Product(normalized, name, Money(price), category)
    inventory = dict(state.inventory)
    inventory[normalized] = InventoryItem(product, quantity, par_level)
    return _add_event(state, f"Added {name} to {normalized}.", inventory=inventory)


def remove_product(state: MachineState, slot: str) -> MachineState:
    require_service(state)
    normalized = validate_slot_code(slot)
    inventory = dict(state.inventory)
    if normalized not in inventory:
        raise InvalidSlotError(f"slot {normalized} does not exist")
    del inventory[normalized]
    return _add_event(state, f"Removed product from {normalized}.", inventory=inventory)


def withdraw_cash(
    state: MachineState, keep_float: Money | None = None
) -> tuple[MachineState, dict[Coin, int]]:
    keep_float = keep_float or DEFAULT_KEEP_FLOAT
    require_service(state)
    removable = state.cash_total - keep_float
    if removable <= Money.zero():
        return _add_event(state, "No cash available to withdraw."), {}
    change = GreedyChangeAlgorithm().make_change(removable, state.cash_reserves) or {}
    reserves = _subtract_counts(state.cash_reserves, change)
    return _add_event(state, f"Withdrew {removable:currency}.", cash_reserves=reserves), change


def exact_change_required(
    price: Money,
    reserves: Mapping[Coin, int],
    algorithm: ChangeAlgorithm[Coin] | None = None,
) -> bool:
    algorithm = algorithm or GreedyChangeAlgorithm()
    for coin in sorted(Coin, key=lambda candidate: candidate.value.cents):
        if coin.value > price:
            return algorithm.make_change(coin.value - price, reserves) is None
    return False


def format_change(change: Mapping[Coin, int]) -> str:
    if not change:
        return "$0.00"
    parts = [
        f"{count} {coin.name.lower()}"
        for coin, count in sorted(
            change.items(), key=lambda item: item[0].value.cents, reverse=True
        )
        if count
    ]
    total = Money.zero()
    for coin, count in change.items():
        total += coin.value * count
    return f"{total:currency} ({', '.join(parts)})"
