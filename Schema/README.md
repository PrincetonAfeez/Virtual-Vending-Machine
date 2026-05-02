# Virtual Vending Machine Schemas

This folder contains simple JSON Schema files for a Virtual Vending Machine project.

The schemas are intentionally lightweight and beginner-friendly. They describe common data objects used in a vending machine application:

- Product
- Inventory item
- Cart item
- Payment
- Transaction
- Vending machine state

## How to use

Use these schemas to validate JSON files, API request/response bodies, or sample data for the vending machine app.

Example:

```json
{
  "id": "A1",
  "name": "Chips",
  "category": "snack",
  "price": 1.50,
  "currency": "USD"
}
```

## Files

| File | Purpose |
|---|---|
| `product.schema.json` | Defines a vending machine product. |
| `inventory-item.schema.json` | Defines stock data for a product slot. |
| `cart-item.schema.json` | Defines an item selected by a customer. |
| `payment.schema.json` | Defines payment information. |
| `transaction.schema.json` | Defines a completed purchase. |
| `vending-machine.schema.json` | Defines the overall machine state. |
| `schema-manifest.json` | Lists all schemas in this folder. |
