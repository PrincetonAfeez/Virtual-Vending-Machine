"""Test money."""

import pytest

from vending.money import Money


def test_decimal_money_adds_exactly() -> None:
    assert Money("0.10") + Money("0.20") == Money("0.30")


def test_money_formats_supported_specs() -> None:
    amount = Money("1.25")
    assert format(amount, "plain") == "1.25"
    assert format(amount, "currency") == "$1.25"
    assert format(amount, "cents") == "125"


def test_money_does_not_multiply_by_money() -> None:
    with pytest.raises(TypeError):
        Money("1.00") * Money("2.00")  # type: ignore[arg-type]

