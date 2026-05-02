"""Money value object backed by :class:`decimal.Decimal`.

The project never uses floats for money. Values are quantized to cents at the
boundary, so arithmetic remains exact for the vending-machine domain.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from functools import total_ordering
from typing import Any

CENT = Decimal("0.01")


@total_ordering
class Money:
    """A small immutable money wrapper.

    Supported format specs:
    - ``plain``: ``1.25``
    - ``currency``: ``$1.25``
    - ``cents``: ``125``
    """

    __slots__ = ("_amount",)

    def __init__(self, amount: Money | Decimal | str | int = "0.00") -> None:
        if isinstance(amount, Money):
            decimal = amount.amount
        elif isinstance(amount, Decimal):
            decimal = amount
        else:
            decimal = Decimal(str(amount))
        self._amount = decimal.quantize(CENT, rounding=ROUND_HALF_UP)

    @property
    def amount(self) -> Decimal:
        return self._amount

    @property
    def cents(self) -> int:
        return int((self._amount * 100).to_integral_value(rounding=ROUND_HALF_UP))

    @classmethod
    def zero(cls) -> Money:
        return cls("0.00")

    @classmethod
    def from_cents(cls, cents: int) -> Money:
        return cls(Decimal(cents) / Decimal(100))

    def _coerce(self, other: Any) -> Money:
        if not isinstance(other, Money):
            raise TypeError(f"expected Money, got {type(other).__name__}")
        return other

    def __add__(self, other: Any) -> Money:
        other_money = self._coerce(other)
        return Money(self._amount + other_money.amount)

    def __radd__(self, other: Any) -> Money:
        if other == 0:
            return self
        return self.__add__(other)

    def __sub__(self, other: Any) -> Money:
        other_money = self._coerce(other)
        return Money(self._amount - other_money.amount)

    def __neg__(self) -> Money:
        return Money(-self._amount)

    def __mul__(self, scalar: int | Decimal | str) -> Money:
        if isinstance(scalar, Money):
            raise TypeError("money can only be multiplied by a scalar")
        return Money(self._amount * Decimal(str(scalar)))

    def __rmul__(self, scalar: int | Decimal | str) -> Money:
        return self.__mul__(scalar)

    def __lt__(self, other: Any) -> bool:
        other_money = self._coerce(other)
        return self._amount < other_money.amount

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Money) and self._amount == other.amount

    def __hash__(self) -> int:
        return hash(self._amount)

    def __bool__(self) -> bool:
        return self._amount != 0

    def __format__(self, spec: str) -> str:
        spec = spec or "currency"
        if spec == "plain":
            return f"{self._amount:.2f}"
        if spec == "currency":
            sign = "-" if self._amount < 0 else ""
            amount = abs(self._amount)
            return f"{sign}${amount:.2f}"
        if spec == "cents":
            return str(self.cents)
        return format(self._amount, spec)

    def __str__(self) -> str:
        return format(self, "currency")

    def __repr__(self) -> str:
        return f"Money({format(self, 'plain')!r})"

