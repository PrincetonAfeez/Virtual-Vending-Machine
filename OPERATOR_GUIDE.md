# Operator Guide

## Daily Start

Run `python -m vending audit` to confirm the saved state is internally consistent. Run `python -m vending report inventory` to see stock levels and below-par slots.

## Restocking

Use `python -m vending restock A1 20 --pin 1234` for a quick restock, or enter `python -m vending admin` and use `restock-all` to refill every below-par slot to its configured par level.

## Pricing

Enter service mode and run `set-price A1 1.75`. Price changes are part of machine state and are saved atomically.

## Cash Collection

Enter service mode and run `withdraw 20.00` to collect cash while leaving a $20 float for change-making. Run `report cash` before and after collection if you want an operator record.

## Reports

`report sales`, `report top-sellers`, and `report failed` read from the append-only transaction log. Failed reports include out-of-stock, exact-change-required, invalid-selection, and cancelled transactions.

