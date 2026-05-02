# Benchmarks

Use the simulation command to measure repeatable runs:

```powershell
Measure-Command { python -m vending simulate --customers 10000 --seed 1 }
```

The simulation uses the same state transitions as the interactive machine, so the benchmark exercises coin insertion, purchase selection, change-making, inventory updates, transaction creation, and persistence.

