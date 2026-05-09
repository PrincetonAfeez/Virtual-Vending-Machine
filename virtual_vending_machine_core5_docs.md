# Architecture Decision Record

## App 38 — Virtual Vending Machine
**Commerce Simulation Group | Document 1 of 5**

### Title
Adopt Immutable Vending-Machine State with Exact Decimal Money, Bounded Change-Making, and JSON Persistence

### Status
Accepted

### Date
2026-05-09

### Context
The Virtual Vending Machine is a command-line simulation of a real vending machine. It must accept money, track inventory, dispense products, return change, support customer and service workflows, persist state across runs, generate operator reports, and run repeatable customer simulations. The main architectural challenge is that vending-machine behavior combines several failure-prone domains: money arithmetic, inventory mutation, cash reserves, service authorization, transaction logging, and recovery after process exit.

A simple procedural script could print a menu and decrement counts, but that design would make it difficult to verify whether failed transactions refunded correctly, whether cash reserves were updated only after completed sales, whether service operations were authorized, and whether simulation runs were reproducible. The project therefore needs a design that makes business rules explicit, testable, and recoverable without becoming a database-backed production system.

### Decision Drivers

- Preserve correctness for money by avoiding binary floating-point arithmetic.
- Keep customer and service workflows testable without terminal I/O.
- Model successful and failed purchases as explicit outcomes rather than vague messages.
- Support realistic change behavior where cash reserves are bounded.
- Persist state and transactions using simple standard-library JSON formats.
- Provide enough operator tooling for reports, restocking, simulation, audit, and reset.
- Stay within the scope of an academic Python CLI package with no runtime third-party dependencies.
- Keep architecture explainable through small modules with clear responsibilities.

### Options Considered

#### Option 1 — Single mutable script with floats and dictionaries
This would be the fastest implementation: hold products in dictionaries, use floats for prices, mutate counts directly, and print output inline. It would have minimal upfront design overhead, but it would make correctness fragile. Float rounding is inappropriate for money, state mutation would make transaction histories harder to reason about, and business logic would become coupled to terminal prompts.

#### Option 2 — Object-oriented mutable `VendingMachine` class
A class with methods such as `insert_coin`, `select_product`, and `restock` would be a familiar approach. It could encapsulate state better than a script, but it would still encourage hidden mutation. Tests would need to check object side effects after each method call, and replaying or auditing a transaction sequence would be less straightforward than comparing explicit before-and-after values.

#### Option 3 — Immutable domain state plus pure transition functions
This approach models the machine as a frozen `MachineState` and implements workflows as functions that return new states. Money is represented by a `Money` value object backed by `Decimal`. Purchases return both a new state and a `TransactionResult`. Persistence, reporting, CLI, and simulation live outside the core state module.

#### Option 4 — Database-backed service with tables for products, inventory, cash, and transactions
A database would provide durable storage and more realistic querying, but it would significantly expand scope. For a CLI learning project, JSON, JSONL, and atomic file replacement are enough to demonstrate persistence and recovery while keeping the code readable.

### Decision
Use immutable domain models and pure transition functions as the core architecture. Store all money as quantized `Decimal` through the `Money` value object. Represent change-making as pluggable algorithms, including a greedy strategy and an optimal bounded dynamic-programming strategy. Persist configuration, products, inventory, machine state, and transactions using standard-library TOML/JSON/JSONL files under `~/.vending` by default. Keep CLI, rendering, reporting, repository I/O, and simulation separate from the transition logic.

### Rationale
This decision gives the project a strong correctness boundary. The vending machine is not just a menu program; it is a state machine. By freezing the machine state and returning new states from each operation, the code makes every transition inspectable. A failed purchase can return `EXACT_CHANGE_REQUIRED` and refund pending inserted money without accidentally committing bills to reserves. A completed purchase can decrement inventory, add pending money to reserves, subtract returned change, clear the balance, update stats, and produce a transaction record in one explicit path.

Exact `Decimal` money prevents the classic floating-point problem where `0.10 + 0.20` fails to equal `0.30`. Bounded change-making is important because vending machines do not have infinite coins. The optimal dynamic-programming algorithm is a stronger architectural choice than relying only on greedy change, because it works even when a denomination system is not canonical.

Using JSON and JSONL keeps the project transparent. Operators can inspect the data files directly, tests can create temporary config/state paths, and the application can avoid runtime dependencies while still demonstrating real persistence.

### Trade-offs Accepted

- Immutable state creates more object replacement code than direct mutation.
- JSON files are simple but not safe for concurrent multi-process writes beyond atomic state replacement.
- PIN hashing demonstrates a security boundary, but it is not a production authentication system because there is no salt, user management, lockout policy, or secret storage service.
- The CLI is intentionally synchronous and terminal-based; it does not model hardware interrupts, card readers, remote telemetry, or concurrent customers.
- JSONL transaction history is append-only and easy to audit, but large files would eventually need indexing or rotation.
- The bundled default catalog is useful for demos, but a production machine would need inventory import/export workflows and stronger validation.

### Consequences

- State transitions can be tested directly without running the interactive CLI.
- Reports and audits can be generated from persisted state and JSONL transaction history.
- Simulations can be repeated by supplying the same seed.
- The application can recover from previous runs by loading state from JSON.
- The change algorithm can be swapped from greedy to optimal through configuration or CLI flags.
- New service commands can usually be added by writing a transition function and then exposing it through the CLI.
- Future work can migrate repositories to SQLite or another storage layer without rewriting the core state functions.

### Superseded By
Not superseded.

### Constitution Alignment
This decision aligns with the project Constitution by prioritizing scope-appropriate architecture, readable decomposition, explicit trade-offs, and verifiable behavior. The project remains a CLI package, but it demonstrates higher-level system thinking through immutable state, exact money handling, persistence, reporting, and simulation.

---

# Technical Design Document

## App 38 — Virtual Vending Machine
**Commerce Simulation Group | Document 2 of 5**

### Purpose & Scope
The Virtual Vending Machine is a command-line Python package that simulates customer purchases and operator workflows for a vending machine. It supports coin and bill insertion, product selection, refunds, bounded change-making, service mode, restocking, price updates, product additions/removals, reports, audit checks, state persistence, transaction logs, and repeatable customer simulation.

The scope is intentionally local and terminal-based. The project does not integrate with payment processors, hardware devices, remote telemetry, user accounts, or a database server. It is designed to demonstrate precise domain modeling and state-driven workflow logic in a maintainable Python package.

### System Context
The system runs as a local CLI application. Its main actors are:

- **Customer** — inserts supported denominations, selects a product, checks balance, cancels, or enters service mode with a PIN.
- **Operator** — uses service mode or direct CLI commands to restock, withdraw cash, modify products, run reports, audit state, simulate customers, or reset the machine.
- **Filesystem** — stores config, product catalog, inventory, current state, and transaction history.
- **Simulation driver** — generates repeatable customer behavior for demos and stress checks.

The machine is not server-based. Each CLI invocation loads configuration and state, performs actions, and saves state where appropriate.

### Component Breakdown

#### `vending/__init__.py`
Exports the public package surface: `Money`, `Coin`, `Mode`, `Product`, and `TransactionOutcome`. It also declares the package version.

#### `vending/money.py`
Defines the `Money` value object. It wraps `Decimal`, quantizes values to cents, supports arithmetic with other `Money` objects, supports scalar multiplication, exposes cents as an integer, and formats values as plain decimal, currency, or cents.

#### `vending/models.py`
Defines the immutable domain model:

- `Coin` enum for penny, nickel, dime, quarter, dollar, five, ten, and twenty.
- `TransactionOutcome` enum for completed and failed transaction categories.
- `Mode` enum for normal, service, maintenance, and locked modes.
- `Product` frozen dataclass.
- `InventoryItem` frozen dataclass.
- `MachineStats` frozen dataclass.
- `MachineState` frozen dataclass with read-only mappings for inventory, cash reserves, pending inserted money, balance, mode, stats, last message, and recent events.
- `Transaction` frozen dataclass for transaction history rows.
- `TransactionResult` frozen dataclass returned by purchase/refund operations.

#### `vending/change.py`
Defines the change-making abstraction and algorithms:

- `ChangeAlgorithm` protocol.
- `denomination_value` helper.
- `GreedyChangeAlgorithm` for largest-denomination-first change.
- `OptimalChangeAlgorithm` for bounded dynamic programming with the fewest pieces.
- `get_change_algorithm` factory.

#### `vending/state.py`
Contains pure workflow transitions. It handles PIN hashing, slot normalization, state initialization, event append behavior, coin insertion, product selection, cancellation, service-mode entry/exit, lock/unlock, restocking, restock-to-par, price setting, product add/remove, cash withdrawal, exact-change detection, and human-readable change formatting.

#### `vending/persistence.py`
Handles configuration and state persistence. It creates default config/catalog/inventory/transactions files, loads TOML config, loads products and inventory, converts `MachineState` to/from dictionaries, loads state from JSON, saves state atomically through a temporary file and `os.replace`, and resets the app to bundled defaults.

#### `vending/repositories.py`
Provides repository abstractions and concrete implementations:

- `InventoryRepository` abstract base.
- `JsonInventoryRepository` for JSON inventory files.
- `InMemoryInventoryRepository` for tests.
- `TransactionRepository` abstract base.
- `JsonlTransactionRepository` for append-only transaction history.
- `InMemoryTransactionRepository` for tests.

#### `vending/reports.py`
Provides operator reports:

- `sales_report`
- `inventory_report`
- `cash_report`
- `top_sellers_report`
- `failed_report`
- `audit_report`
- `format_report` with plain, JSON, and CSV support.

#### `vending/simulation.py`
Implements repeatable customer simulation. It defines customer strategies such as random, budget, picky, and exact-change customers. `run_simulation` applies simulated purchases against real state transitions and returns a `SimulationResult` containing the final state, transactions, and summary.

#### `vending/renderers.py`
Defines state-to-string renderers for terminal output:

- `ClassicRenderer`
- `CompactRenderer`
- `MinimalRenderer`
- `get_renderer` factory.

Renderers do not own state transitions. They format current inventory, balance, cash reserve, exact-change status, status messages, and recent events.

#### `vending/ansi.py`
Provides a tiny ANSI helper for colored output. It supports green, yellow, red, dim, and bright text.

#### `vending/cli.py`
Defines the argparse interface, runtime construction, interactive loop, command handlers, report commands, restock command, simulation command, audit command, reset command, persistence hooks, transaction appending, receipts, and help text.

#### `vending/exceptions.py`
Defines the custom exception hierarchy:

- `VendingError`
- `InsufficientFundsError`
- `OutOfStockError`
- `InvalidCoinError`
- `InvalidSlotError`
- `CannotMakeChangeError`
- `ServiceModeRequiredError`
- `AccessDeniedError`

#### `vending/__main__.py`
Thin entrypoint for `python -m vending`.

### Module Dependency Graph

```text
vending.cli
  -> change, exceptions, models, money, persistence, renderers,
     reports, repositories, simulation, state

vending.state
  -> change, exceptions, models, money

vending.models
  -> money

vending.change
  -> models, money

vending.persistence
  -> importlib.resources, models, money, state

vending.repositories
  -> exceptions, models, persistence

vending.reports
  -> models, money

vending.simulation
  -> change, models, money, state

vending.renderers
  -> ansi, change, models, state

vending.__main__
  -> cli
```

The direction of dependencies keeps the domain center clear: `money`, `models`, `change`, and `state` do not depend on the CLI. Persistence and repositories know how to serialize state, but they do not decide business rules. Reports and renderers consume state and transactions. The CLI orchestrates all other components.

### Core Algorithms & Logic

#### Money normalization
Every `Money` object is initialized from another `Money`, `Decimal`, string, or integer. The value is converted to `Decimal` and quantized to `0.01` with `ROUND_HALF_UP`. Arithmetic returns new `Money` objects. This keeps money representation stable at the boundary and avoids float rounding errors.

#### Coin insertion
1. Confirm the machine is in `NORMAL` mode.
2. Convert string tokens such as `q`, `quarter`, `$1`, or `five` into `Coin` enum values.
3. Add the coin value to the current balance.
4. Reject insertion if the new balance exceeds the configured maximum balance.
5. Increment the coin count in `pending_inserted`.
6. Return a new `MachineState` with updated balance, pending inserted money, last message, and events.

#### Product selection
1. Confirm customer purchases are allowed in `NORMAL` mode.
2. Normalize and validate the slot code.
3. Reject unknown or empty slots with an explicit transaction outcome.
4. Reject out-of-stock products.
5. If the customer has insufficient funds, keep the balance and return an `INSUFFICIENT_FUNDS` result without committing cash.
6. Compute change due as `current_balance - product.price`.
7. Ask the selected change algorithm to produce bounded change from existing cash reserves.
8. If change is impossible, refund the pending inserted coins and clear the balance.
9. If change is possible, decrement inventory, add pending inserted money to reserves, subtract returned change, clear pending state, update stats, create a completed transaction, and return the new state plus result.

#### Cancellation
1. If there is no current balance, return a cancelled result with no refund.
2. If there is a balance, return exactly the pending inserted denominations.
3. Clear pending inserted money and current balance.
4. Update failed transaction stats and create a cancellation transaction.

#### Greedy change-making
1. Convert the requested `Money` amount to cents.
2. Sort available denominations by descending value.
3. For each denomination, use as many as possible without exceeding the remaining amount or reserve count.
4. Return the denomination map when remaining amount reaches zero.
5. Return `None` when bounded reserves cannot satisfy the amount.

#### Optimal bounded change-making
1. Convert the target amount to cents.
2. Initialize a dynamic-programming table from `0` cents to target cents.
3. For each denomination and each available piece, update reachable amounts in descending order.
4. Keep the candidate with the fewest total pieces for each amount.
5. Return the counted denominations for the target amount, or `None` if unreachable.

This algorithm is more general than greedy and is included because real change-making is bounded by available reserves.

#### Service-mode transition
1. Hash the supplied PIN with SHA-256.
2. Compare it to the configured service PIN hash.
3. On match, return a new state in `SERVICE` mode.
4. On mismatch, raise `AccessDeniedError`.

Service operations call `require_service`, so restock, price setting, product mutation, cash withdrawal, and locking are not available in customer mode.

#### Persistence bootstrapping
1. Load or create the config file under `~/.vending/config.toml` by default.
2. Fill the default service PIN hash for first-run config.
3. Ensure product, inventory, and transaction files exist.
4. Load current machine state from `state.json` if present.
5. If no state file exists, build initial state from products, inventory, and configured starting float.
6. Save state through a temp file and `os.replace` to reduce partial-write risk.

#### Reporting
Reports read from state and transaction repositories. Sales reports aggregate completed transactions and revenue. Inventory reports flag below-par slots. Cash reports summarize denomination reserves. Failed reports list non-completed transaction records. Audit reports check invariants such as current balance matching pending inserted money and non-negative inventory/cash counts.

#### Simulation
1. Seed a local `random.Random` object.
2. Choose a customer type for each simulated customer.
3. Let the customer pick an available product.
4. Generate a coin sequence.
5. Run the same `insert_coin` and `select_product` state transitions used by real customer flows.
6. Append any generated transaction results.
7. Cancel if an insufficient-funds path leaves a balance.
8. Continue after operational exceptions and count them in the summary.
9. Return final state, transactions, and a summary dictionary.

### Data Structures

#### `Money`
```python
Money("1.25")
```
Stores a quantized `Decimal` internally and exposes `.amount` and `.cents`.

#### `Product`
```python
Product(slot="A1", name="Water", price=Money("1.25"), category="drink")
```
Represents the sellable catalog item.

#### `InventoryItem`
```python
InventoryItem(product=product, quantity=8, par_level=4)
```
Combines product metadata with stock count and restock threshold.

#### `MachineState`
```python
MachineState(
    inventory={"A1": InventoryItem(...)},
    cash_reserves={Coin.QUARTER: 8},
    pending_inserted={Coin.DOLLAR: 2},
    current_balance=Money("2.00"),
    mode=Mode.NORMAL,
    stats=MachineStats(...),
    last_message="Inserted $1.00. Balance: $2.00.",
    events=(...),
)
```
The central immutable state snapshot.

#### `Transaction`
```python
Transaction(
    started_at="...",
    coins_inserted={Coin.DOLLAR: 2},
    slot_selected="A1",
    outcome=TransactionOutcome.COMPLETED,
    change_returned={Coin.QUARTER: 3},
    completed_at="...",
    message="Dispensed Water. Change: $0.75 ...",
    paid=Money("2.00"),
    price=Money("1.25"),
    product_name="Water",
)
```
The JSONL audit unit for transaction history.

#### `Config`
```python
Config(
    config_path=Path(...),
    data_dir=Path(...),
    currency="USD",
    algorithm="optimal",
    renderer="classic",
    max_balance=Money("20.00"),
    service_pin_hash="...",
    starting_float={Coin.QUARTER: 20, ...},
    state_file=Path(...),
    products_file=Path(...),
    inventory_file=Path(...),
    transactions_file=Path(...),
)
```
Runtime configuration resolved from TOML and defaults.

### State Management
`MachineState` is frozen, and its mapping fields are converted to read-only `MappingProxyType` wrappers. State changes occur through functions that return a new `MachineState`. Recent events are bounded to the last five entries so the rendered display does not grow without limit.

Persistent state is saved to JSON after interactive commands and command-line operations that mutate state. Transaction history is append-only JSONL. Simulation returns a new state and a tuple of transactions, then the CLI persists both.

### Error Handling Strategy
The project uses a custom `VendingError` hierarchy for domain failures. The CLI catches `VendingError` and returns exit code `2` for command-level domain errors. Interactive mode catches `VendingError`, `ValueError`, and `IndexError`, prints an error, and continues the session.

Some purchase failures are not raised as exceptions because they are expected transaction outcomes. Examples include insufficient funds, out of stock, invalid selection, exact-change-required, cancellation, and machine-locked states. These are represented as `TransactionOutcome` values and can be recorded, reported, and audited.

### External Dependencies
Runtime dependencies: none beyond the Python standard library.

Development dependencies:

- pytest
- pytest-cov
- hypothesis
- ruff
- mypy

The package requires Python 3.11 or newer.

### Concurrency Model
The application is single-process and synchronous. There is no threaded input loop, no async runtime, and no locking for concurrent processes. Atomic state save reduces partial-write risk but does not provide full multi-writer concurrency control. JSONL transactions are appended by the active process.

### Known Limitations

- No hardware integration, payment API, card processing, or real coin acceptor simulation.
- No database, file locking, transaction isolation, or concurrent customer support.
- Service PIN hashing uses SHA-256 but no salt or secret manager.
- The simulation is useful for repeatability but is not a statistically validated demand model.
- Report formatting is intentionally simple and local.
- The default catalog is bundled and small.
- JSONL history may need rotation or indexing for very long-running use.
- Refunds are based on pending inserted denominations, not a physical coin hopper model for returned inserted money.

### Design Patterns Used

- **Value Object:** `Money` represents currency safely.
- **Immutable State:** `MachineState` and domain records are frozen or read-only.
- **Pure Function Transitions:** customer and service workflows return new states.
- **Strategy Pattern:** change algorithms and renderers are swappable.
- **Repository Pattern:** inventory and transaction storage have JSON and in-memory implementations.
- **Factory Function:** `get_change_algorithm` and `get_renderer` resolve names to implementations.
- **Append-only Log:** transaction history is stored as JSONL.
- **Simulation Driver:** repeatable seeded simulation exercises the same transition path as real users.

### Constitution Alignment
The project shows progressive complexity beyond a basic CLI app. It demonstrates Python fundamentals, architectural decomposition, state management, persistence, error handling, testing, and reflection-worthy trade-offs while staying scoped as a local standard-library package.

---

# Interface Design Specification

## App 38 — Virtual Vending Machine
**Commerce Simulation Group | Document 3 of 5**

### Invocation Syntax

Installed console script:

```bash
vending [global-options] <command> [command-options]
```

Module invocation:

```bash
python -m vending [global-options] <command> [command-options]
```

Default command when omitted:

```bash
vending run
```

### Global Options

| Option | Type | Required | Default | Valid Values | Description |
|---|---:|---:|---|---|---|
| `--config` | path | No | `~/.vending/config.toml` | readable/writable TOML path | Overrides the config file location. |
| `--renderer` | string | No | config renderer | `classic`, `compact`, `minimal` | Selects terminal renderer. |
| `--no-color` | flag | No | `False` | present/absent | Disables ANSI color. |
| `--state-file` | path | No | config state file | JSON path | Overrides persisted machine state file. |
| `--algorithm` | string | No | config algorithm | `greedy`, `optimal` | Selects change-making strategy. |

### Command Reference

| Command | Syntax | Description |
|---|---|---|
| `run` | `vending run` | Starts interactive customer mode. |
| `admin` | `vending admin` | Prompts for service PIN and starts directly in service mode. |
| `report` | `vending report <type> [options]` | Generates sales, inventory, cash, top-sellers, or failed report. |
| `restock` | `vending restock <slot> <quantity> --pin <pin>` | Restocks a slot from command line. |
| `restock --all` | `vending restock --all --pin <pin>` | Restocks all low slots to par. |
| `simulate` | `vending simulate --customers N --seed S` | Runs repeatable simulated customers. |
| `audit` | `vending audit` | Checks persisted state invariants. |
| `reset` | `vending reset --factory [--yes]` | Restores bundled defaults. |

### Report Command Arguments

| Argument / Flag | Type | Required | Default | Valid Values | Description |
|---|---:|---:|---|---|---|
| `type` | string | Yes | none | `sales`, `inventory`, `cash`, `top-sellers`, `failed` | Report type. |
| `--by-day` | flag | No | `False` | present/absent | Groups sales by day. |
| `--by-slot` | flag | No | `False` | present/absent | Groups sales by slot. |
| `--by-hour` | flag | No | `False` | present/absent | Groups sales by hour. |
| `--limit` | integer | No | `10` | positive integer | Limits top-sellers rows. |
| `--format` | string | No | `plain` | `plain`, `json`, `csv` | Report output format. |

### Restock Command Arguments

| Argument / Flag | Type | Required | Default | Description |
|---|---:|---:|---|---|
| `slot` | string | Required unless `--all` | none | Slot code such as `A1`. |
| `quantity` | integer | Required unless `--all` | none | Amount to add. |
| `--all` | flag | No | `False` | Restocks all below-par slots to par. |
| `--pin` | string | No | prompt | Service PIN. |

### Simulate Command Arguments

| Argument / Flag | Type | Required | Default | Description |
|---|---:|---:|---|---|
| `--customers` | integer | No | `100` | Number of simulated customers. |
| `--seed` | integer | No | random | Seed for repeatable behavior. |
| `--format` | string | No | `plain` | `plain` or `json`. |

### Reset Command Arguments

| Argument / Flag | Type | Required | Default | Description |
|---|---:|---:|---|---|
| `--factory` | flag | Yes | absent | Required guard for destructive reset. |
| `--yes` | flag | No | absent | Skips the `RESET` confirmation prompt. |

### Interactive Customer Commands

| Command | Description |
|---|---|
| `insert quarter` | Inserts a quarter. Any supported coin/bill token can follow `insert`. |
| `p` | Shortcut for penny. |
| `n` | Shortcut for nickel. |
| `d` | Shortcut for dime. |
| `q` | Shortcut for quarter. |
| `$` | Shortcut for one dollar. |
| `select A1` | Selects slot `A1`. |
| `A1` | Direct slot selection. |
| `cancel` | Cancels current transaction and refunds pending inserted money. |
| `balance` | Prints current balance. |
| `service 1234` | Enters service mode when PIN is valid. |
| `help` | Prints help. |
| `exit` / `quit` | Ends interactive loop. |

### Interactive Service Commands

| Command | Description |
|---|---|
| `restock A1 20` | Adds stock to a slot. |
| `restock-all` | Restocks low slots to par. |
| `withdraw 20.00` | Withdraws cash while keeping the supplied float amount. |
| `set-price A1 1.75` | Updates product price. |
| `add-product D1 "Protein Bar" 2.50 snack 8 4` | Adds or replaces a product in a slot. |
| `remove-product D1` | Removes product from slot. |
| `set-par A1 5` | Sets par level. |
| `report inventory` | Prints a service-mode report. |
| `audit-log` | Prints recent transactions. |
| `lock` | Locks the machine. |
| `unlock 1234` | Unlocks with PIN. |
| `exit-service` | Returns to normal mode. |

### Input Contract

#### Slot codes
Slot codes must match the pattern `A1` through `H9`, case-insensitive. Codes are normalized to uppercase.

#### Money values
Money values are parsed through `Decimal(str(value))` and quantized to cents. Examples: `1`, `1.25`, `20.00`.

#### Coin and bill tokens
Accepted customer tokens include:

- penny: `p`, `penny`, `1c`
- nickel: `n`, `nickel`, `5c`
- dime: `d`, `dime`, `10c`
- quarter: `q`, `quarter`, `25c`
- dollar: `$`, `$1`, `1`, `dollar`, `one`
- five: `$5`, `5`, `five`
- ten: `$10`, `10`, `ten`
- twenty: `$20`, `20`, `twenty`

#### Config file
Config is TOML. The default path is `~/.vending/config.toml`. Expected keys include currency, algorithm, renderer, maximum balance, service PIN hash, starting float, and file paths for state/products/inventory/transactions.

#### JSON files
Product and inventory files are JSON. State is JSON. Transactions are JSONL, one transaction per line.

### Output Contract

#### Interactive renderers
`classic` renders a bordered machine display with products, prices, stock status, exact-change indicators, machine status, and recent history.

`compact` renders a dense text table suitable for terminal inspection.

`minimal` emits pipe-delimited machine and inventory rows:

```text
normal|0.00|Select an item.
A1|Water|1.25|8|4
```

#### Reports
Reports can emit plain nested text, JSON, or CSV depending on `--format`.

#### Simulation summary
Plain simulation output prints key-value rows. JSON simulation output emits a summary object containing customers, seed, outcomes, successful transaction count, remaining inventory, cash total, and state transaction count.

#### Purchase receipt
Completed purchase receipts include product, price, paid amount, and change. Failed purchases print the result message.

### Exit Code Reference

| Exit Code | Meaning |
|---:|---|
| `0` | Command completed successfully. |
| `1` | Audit found an invariant issue, reset was cancelled, or help/fallback path occurred. |
| `2` | Domain error caught by CLI, such as invalid vending operation. |
| nonzero from Python/argparse | Invalid command-line syntax or unhandled runtime issue. |

### Error Output Behavior
The top-level CLI prints caught `VendingError` messages to stderr as:

```text
Error: <message>
```

Interactive mode catches domain and value errors, prints:

```text
Error: <message>
```

and continues the session.

### Environment Variables
No application-specific environment variables are defined. Standard environment behavior still applies:

- `HOME` affects expansion of `~/.vending`.
- Terminal ANSI support affects how colors display.

### Configuration Files
Default config path:

```text
~/.vending/config.toml
```

Created on first run when missing. CLI options override selected config values for that invocation. Relative file paths in config resolve under the config directory.

### Side Effects
The application may create, read, update, or delete:

```text
~/.vending/config.toml
~/.vending/products.json
~/.vending/inventory.json
~/.vending/state.json
~/.vending/transactions.jsonl
```

`reset --factory` can remove and recreate bundled default data files. `simulate`, interactive purchases, restock, service commands, and reset can mutate persisted state.

### Usage Examples

#### Start the interactive machine
```bash
python -m vending run
```

#### Insert money and buy a product interactively
```text
insert dollar
insert quarter
select A1
```

#### Run as admin
```bash
python -m vending admin
```

#### Generate an inventory report
```bash
python -m vending report inventory
```

#### Generate a JSON cash report
```bash
python -m vending report cash --format json
```

#### Restock a slot
```bash
python -m vending restock A1 10 --pin 1234
```

#### Simulate customers reproducibly
```bash
python -m vending simulate --customers 100 --seed 42 --format json
```

#### Audit persisted state
```bash
python -m vending audit
```

#### Reset to bundled defaults
```bash
python -m vending reset --factory --yes
```

#### Intentional failure: unknown command in interactive mode
```text
vending> dance
Unknown command. Type help.
```

#### Intentional failure: service command outside service mode
```text
vending> restock A1 10
Unknown command. Type help.
```

or through direct transition calls, service-only functions raise `ServiceModeRequiredError` when not in service mode.

---

# Runbook

## App 38 — Virtual Vending Machine
**Commerce Simulation Group | Document 4 of 5**

### Prerequisites

- Python 3.11 or newer.
- A local terminal environment.
- Write access to the user home directory or an alternate config/state path.
- No runtime third-party packages are required.
- For development: pytest, pytest-cov, hypothesis, ruff, and mypy through the `dev` extra.

### Installation Procedure

From a clean checkout:

```bash
python -m venv .venv
```

Activate the environment.

PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

macOS/Linux:

```bash
source .venv/bin/activate
```

Install the application:

```bash
python -m pip install -e .
```

Install development tooling:

```bash
python -m pip install -e ".[dev]"
```

Alternative from `requirements.txt`:

```bash
python -m pip install -r requirements.txt
```

### Configuration Steps

First run creates the default app directory and files:

```bash
python -m vending run
```

Expected default directory:

```text
~/.vending/
```

Expected files:

```text
config.toml
products.json
inventory.json
state.json
transactions.jsonl
```

The default service PIN is `1234`. For a real personal demo, replace `service_pin_hash` in config with the output of:

```python
from vending.state import hash_pin
print(hash_pin("your-pin"))
```

For tests or isolated runs, use explicit paths:

```bash
python -m vending --config ./tmp/config.toml --state-file ./tmp/state.json run
```

### Standard Operating Procedures

#### Start customer mode
```bash
python -m vending run
```

#### Buy a product
```text
insert dollar
insert quarter
select A1
```

#### Cancel a transaction
```text
insert dollar
cancel
```

#### Enter service mode
```text
service 1234
```

#### Restock inside service mode
```text
restock A1 20
restock-all
exit-service
```

#### Restock from command line
```bash
python -m vending restock A1 10 --pin 1234
```

#### Run reports
```bash
python -m vending report sales --by-day
python -m vending report inventory
python -m vending report cash --format json
python -m vending report top-sellers --limit 5
python -m vending report failed
```

#### Run simulation
```bash
python -m vending simulate --customers 100 --seed 42
```

#### Audit state
```bash
python -m vending audit
```

#### Restore bundled defaults
```bash
python -m vending reset --factory --yes
```

### Health Checks

#### Import package
```bash
python - <<'PY'
import vending
print(vending.__version__)
PY
```

#### Show CLI help
```bash
python -m vending --help
```

#### Create isolated config and run audit
```bash
python -m vending --config ./health/config.toml --state-file ./health/state.json audit
```

Expected output includes:

```text
ok: True
```

#### Run a short simulation
```bash
python -m vending --config ./health/config.toml --state-file ./health/state.json simulate --customers 5 --seed 42 --format json
```

Expected output is JSON containing:

```json
{
  "customers": 5,
  "seed": 42,
  "outcomes": {}
}
```

The exact outcomes depend on catalog and state, but the keys `customers`, `seed`, and `outcomes` should be present.

#### Run tests
```bash
python -m pytest -q
```

Project pytest configuration includes coverage for the `vending` package and a fail-under threshold of 95%.

### Expected Output Samples

#### Cash report, plain format
```text
total: 20.00
reserves:
  - denomination=TWENTY, value=20.00, count=0, total=0.00
  - denomination=TEN, value=10.00, count=0, total=0.00
```

#### Simulation, plain format
```text
customers: 100
seed: 42
outcomes: {'completed': 83, 'exact_change_required': 5}
successful_transactions: 83
remaining_inventory: 42
cash_total: 135.75
state_transactions: 88
```

#### Successful receipt
```text
Receipt
-------
Product: Water
Price:   $1.25
Paid:    $2.00
Change:  $0.75 (3 quarter)
```

### Known Failure Modes

| Symptom | Probable Cause | Diagnostic Step | Resolution |
|---|---|---|---|
| `Error: incorrect service PIN` | Wrong PIN supplied | Confirm config hash and intended PIN | Use correct PIN or update `service_pin_hash`. |
| `unsupported coin or bill` | Invalid insert token | Try `q`, `quarter`, `$1`, `five` | Use supported denomination token. |
| `maximum balance is $20.00` | Customer exceeded configured max balance | Check `max_balance` in config | Insert smaller amount or raise configured max. |
| `Exact change required` | Cash reserves cannot return change | Run `report cash` | Restock cash reserves or use exact payment. |
| `slot codes must look like A1 through H9` | Malformed slot | Check slot format | Use valid slot code. |
| `service mode required` | Operator transition called outside service mode | Check current mode | Enter service mode first. |
| `ok: False` from audit | State invariant issue | Read audit issue list | Restore from backup, reset factory, or inspect state JSON. |
| Argparse usage error | Invalid CLI syntax | Run `vending --help` | Correct command/flags. |

### Troubleshooting Decision Tree

```text
Command fails before app starts
├─ Is the package installed?
│  ├─ No: run python -m pip install -e .
│  └─ Yes: run python -m vending --help
├─ Is Python >= 3.11?
│  ├─ No: install a supported version
│  └─ Yes: inspect command syntax

Interactive purchase fails
├─ Is the machine in normal mode?
│  ├─ No: unlock or exit service mode
│  └─ Yes
├─ Is the slot valid and stocked?
│  ├─ No: restock or choose another slot
│  └─ Yes
├─ Is balance >= price?
│  ├─ No: insert more money
│  └─ Yes
└─ Can the machine make change?
   ├─ No: use exact change or replenish reserves
   └─ Yes: inspect transaction log if still failing

Reports look wrong
├─ Are transactions being appended?
│  ├─ No: check transactions.jsonl path
│  └─ Yes
├─ Is state-file override pointing elsewhere?
│  ├─ Yes: use consistent --state-file
│  └─ No: run audit

State seems corrupted
├─ Run vending audit
├─ Inspect ~/.vending/state.json
├─ Restore known-good state if available
└─ Use vending reset --factory --yes if acceptable
```

### Dependency Failure Handling
Runtime dependency risk is low because the app uses the standard library. Development commands can fail if pytest, coverage, Ruff, or mypy are not installed. Install the dev extra:

```bash
python -m pip install -e ".[dev]"
```

### Recovery Procedures

#### Recover from bad state
1. Run `python -m vending audit`.
2. If audit reports issues, copy current files for inspection:
   ```bash
   cp -r ~/.vending ~/.vending.backup
   ```
3. Restore from a known-good backup, or reset:
   ```bash
   python -m vending reset --factory --yes
   ```

#### Recover from wrong config
1. Move the config aside:
   ```bash
   mv ~/.vending/config.toml ~/.vending/config.toml.bak
   ```
2. Start the app to regenerate defaults:
   ```bash
   python -m vending run
   ```
3. Reapply only known-good settings.

#### Recover from transaction log issue
1. Copy `transactions.jsonl` for analysis.
2. Remove malformed lines if any are clearly invalid JSON.
3. Run reports again.
4. If reports still fail, start with an empty transaction log after backing up the old one.

### Logging Reference
The application does not use a structured logging framework. Operational history is stored in:

- `MachineState.events` — the last five state events rendered in the UI.
- `transactions.jsonl` — append-only transaction records.
- `state.json` — current state snapshot.
- report output — computed views from state and transactions.

### Maintenance Notes

- Keep `products.json` and `inventory.json` schema stable when editing by hand.
- Use `Money` formatting strings, not floats, when modifying product prices.
- Be careful when changing `Coin` enum names because JSON transaction persistence stores coin names.
- Keep service mode protections in `state.py`; do not enforce them only in the CLI.
- When adding report formats, keep JSON output machine-readable and deterministic.
- When adding new simulation customer types, ensure they use the same state transition functions as real commands.
- If the app grows beyond local CLI scope, consider file locking, SQLite, or transaction journaling.

### Constitution Alignment
The runbook provides reproducible setup, expected commands, health checks, known failure modes, recovery paths, and testing instructions. This satisfies the Constitution’s requirement that behavior be verifiable and operationally understandable.

---

# Lessons Learned

## App 38 — Virtual Vending Machine
**Commerce Simulation Group | Document 5 of 5**

### Project Summary
The Virtual Vending Machine is a state-driven CLI simulation of vending-machine operations. It supports customer purchases, service mode, restocking, cash withdrawal, product management, bounded change-making, JSON persistence, reports, audit checks, and seeded customer simulation. The strongest architectural feature is that the business logic lives in immutable state transitions instead of being hidden inside terminal prompts.

### Original Goals vs. Actual Outcome
The original goal was to build a vending machine that could accept money and dispense products. The actual outcome is broader and more system-oriented. The final project includes exact money handling, multiple change algorithms, state persistence, JSONL transactions, reporting, auditing, service authorization, factory reset, and repeatable simulation.

That expansion could have become scope creep, but the implementation remains cohesive because every feature relates to the central vending-machine state model.

### Technical Decisions That Paid Off

#### Exact `Decimal` money
Using a dedicated `Money` value object prevented float errors and made currency formatting consistent. This decision matters because every purchase, refund, revenue total, and cash report depends on exact cents.

#### Immutable machine state
Returning new `MachineState` objects made transition behavior easier to test and reason about. Tests can compare old and new state without worrying that a function mutated the original object.

#### Explicit transaction outcomes
Modeling outcomes such as `COMPLETED`, `INSUFFICIENT_FUNDS`, `OUT_OF_STOCK`, `CANCELLED`, and `EXACT_CHANGE_REQUIRED` created clearer behavior than relying only on printed messages.

#### Bounded change-making
A vending machine has finite reserves. Modeling reserves in the change algorithm made the simulation more realistic and created better failure paths.

#### JSONL transaction log
JSONL is simple, append-only, inspectable, and useful for reports. It fits the project scale better than a database while still demonstrating persistence.

#### In-memory repositories for tests
Providing in-memory inventory and transaction repositories made persistence behavior testable without relying on global user files.

#### Seeded simulation
Simulation became more useful because it is repeatable. A seed lets the developer reproduce outcomes and compare algorithm or inventory changes.

### Technical Decisions That Created Debt

#### Service PIN hashing is simple
Hashing a PIN with SHA-256 is better than storing plain text, but it is not production-grade authentication. A stronger design would use salt, rate limiting, separate operator identities, and protected secret storage.

#### Filesystem persistence has concurrency limits
Atomic state save helps avoid partial state files, but the system does not lock files across processes. Two simultaneous CLI sessions could still conflict.

#### Reports are computed directly from JSONL
For small logs, this is fine. For large transaction histories, report generation would need indexing, aggregation snapshots, or a database.

#### CLI command parsing is manual inside interactive mode
Interactive command handling uses `shlex.split` and conditional branches. It is readable, but as commands grow, it may benefit from a command registry or mini-parser.

#### Refund semantics are simplified
Refunds return pending inserted denominations, which is reasonable for a virtual machine but not necessarily how every physical machine would route inserted cash.

### What Was Harder Than Expected

The hard part was not displaying products. The hard part was correctly separating pending money from committed cash reserves. A purchase should only commit inserted money if the product can be dispensed and change can be returned. Exact-change failure requires refunding the pending money without changing inventory or reserves.

Service mode also introduced subtle complexity. Restock, price changes, product additions, product removals, withdrawals, and locks must be blocked unless the machine is in the correct mode. That is why authorization belongs in `state.py`, not only in the CLI.

Change-making was another important challenge. Greedy change is easy to write, but bounded optimal change requires thinking in cents and considering reserve counts.

### What Was Easier Than Expected

JSON and JSONL were a good fit. Because the domain objects already had `to_dict` and `from_dict` methods, persistence stayed understandable. Reports were also easier because transaction outcomes and money fields were explicit.

The renderer split helped keep terminal output from complicating the core model. Once the machine state was stable, classic, compact, and minimal output could all be written as views over the same data.

### Python-Specific Learnings

- `Decimal` should be used for money instead of float.
- `dataclass(frozen=True)` is useful for learner-scale immutable domain models.
- `MappingProxyType` helps protect mapping fields from accidental mutation.
- `Enum` is useful when outcomes and modes must be explicit and reportable.
- `os.replace` is a simple standard-library way to make state saves more atomic.
- `importlib.resources` can ship default config and product data with a package.
- `argparse` remains sufficient for a multi-command CLI when commands are scoped clearly.
- `shlex.split` is useful for quoted interactive commands such as product names.
- `random.Random(seed)` is better than global random state for repeatable simulations.

### Architecture Insights

This project shows that immutability is not only useful for games or algorithm visualizers. It also fits transactional business logic. A vending machine has clear before-and-after states, and every operation can be modeled as a transition.

The project also shows the value of keeping side effects at the edges. The state module does not print, prompt, save files, or parse CLI flags. That makes it more reusable by the interactive loop, direct admin commands, reports, and simulation.

A third insight is that failures are part of the domain. Out-of-stock, exact-change-required, invalid selection, and insufficient funds are not exceptions in the user experience; they are expected outcomes worth recording.

### Testing Gaps

The repository includes tests for exact money arithmetic, change algorithms, immutable state behavior, successful purchases, exact-change refunds, service-mode enforcement, persistence/repositories, and CLI smoke paths. Useful future tests would include:

- More property-based tests for `Money` arithmetic and change-making.
- More CLI interaction tests for service commands.
- Golden output tests for renderers and reports.
- Corrupted JSON/JSONL recovery tests.
- Multi-step scenario tests covering insert, cancel, insert, purchase, report.
- Simulation reproducibility tests comparing full summary output for a fixed seed.
- Audit failure tests that intentionally construct invalid state.

### Reusable Patterns Identified

- Immutable state plus transition functions.
- Value object for dangerous primitive domains such as money.
- Strategy pattern for algorithms that may vary.
- Repository abstraction with JSON and in-memory implementations.
- Append-only JSONL event/transaction history.
- Renderer classes that turn state into strings without owning logic.
- CLI orchestration that loads config, builds runtime dependencies, invokes pure logic, persists results, and handles errors.
- Seeded simulation for repeatable demo and stress behavior.

### If I Built This Again

I would keep the immutable state and `Money` object. Those are the right foundation. I would consider adding a command registry for interactive service commands to reduce the length of `handle_service_command`. I would also separate product catalog editing from inventory editing more explicitly, because real vending systems distinguish catalog metadata from machine slot stock.

For a larger version, I would move persistence to SQLite, add file locking or transactions, create structured logs, improve PIN handling, and add export/import commands for catalog and inventory. I would also make reports more queryable by date range and category.

### Open Questions

- Should pending inserted money be modeled as physically separate from cash reserves until purchase completion, as it is now, or should a more hardware-like escrow model be introduced?
- Should exact-change-required be displayed before a customer inserts money for products that cannot currently return change?
- Should restocking product quantity and restocking cash reserves be separate operator workflows?
- Should audit compare transaction history revenue against current reserves and inventory deltas?
- Should service mode have a session timeout?
- Should simulation support customer preferences loaded from a config file?
- Should the app rotate or compact transaction logs after a threshold?

### Constitution Reflection
The project is a strong fit for the Constitution’s final evaluation standard. It is authentic, scoped as a CLI package, architecturally intentional, verifiable through tests and smoke commands, and reflective about trade-offs. Its imperfections are teachable: persistence is simple, security is not production-grade, and simulation is limited. Those weaknesses do not undermine the learning value; they clarify what the next refactor would address.
