# Architecture

## Decimal Money

Money is represented by `vending.money.Money`, a tiny immutable wrapper around `decimal.Decimal`. The class quantizes values to cents and intentionally avoids division so money arithmetic stays explicit and exact.

## Immutable State

`MachineState` is a frozen dataclass. Its inventory, reserves, pending coins, current balance, mode, stats, and recent events describe the whole machine at one point in time. Operations such as `insert_coin`, `select_product`, and `cancel_transaction` return a new state instead of mutating the old one.

## Explicit Modes

The mode enum is the machine-level state machine: `NORMAL`, `SERVICE`, `MAINTENANCE`, and `LOCKED`. Customer actions only work in normal mode. Operator actions require service mode, and a PIN hash gates entry.

## Change Strategy

`ChangeAlgorithm` is a protocol with two implementations. `GreedyChangeAlgorithm` is fast and appropriate for US denominations. `OptimalChangeAlgorithm` uses bounded dynamic programming so it can prove the fewest pieces for arbitrary denomination sets.

## Data Separation

The catalog (`products.json`) says what products exist. Inventory says how many units are stocked and what par levels operators want. State records the live machine. Transactions are append-only JSONL audit entries.

## Simulation

Human commands and simulated customers both drive the same transition functions. That keeps demos honest: if simulation can buy, fail, refund, and deplete stock, the interactive machine is exercising the same logic.

## Transition Table

| Operation | NORMAL | SERVICE | LOCKED |
| --- | --- | --- | --- |
| Insert coin | allowed | rejected | rejected |
| Select product | allowed | rejected | rejected |
| Cancel | allowed | allowed if balance exists | allowed if balance exists |
| Enter service | allowed with PIN | already service | allowed with PIN through unlock |
| Restock/set price/withdraw | rejected | allowed | rejected |
| Lock | rejected | allowed | already locked |

