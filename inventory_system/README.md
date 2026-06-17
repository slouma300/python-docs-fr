# Inventory Stock System

This is a standalone stock management app added under `inventory_system/`.
It uses Python's standard library, SQLite, and a small browser UI.

There are now two versions:

- `app.py` + `static/` - local Python/SQLite version
- `vercel_app/` - Vercel-ready static version, using browser storage until
  Supabase is connected later

## Features

- Stock in to a named location
- Stock out from a named location
- Transfer stock from one location to another
- Barcode lookup by hardware scanner, typed input, or supported camera browser
- Current stock by product and location
- Stock movement history
- SQLite persistence with an audit trail of every movement

## Run locally

From the repository root:

```bash
python3 inventory_system/app.py --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

The default database is created at:

```text
inventory_system/inventory.db
```

You can choose another database path:

```bash
python3 inventory_system/app.py --db /tmp/inventory.db
```

## Barcode scanning

Most USB and Bluetooth barcode scanners work like a keyboard. Click the
barcode field, scan the item, and press Enter or use the lookup button.

The "Start camera scan" button uses the browser `BarcodeDetector` API when it
is available. If your browser does not support it, use a hardware scanner or
type the barcode manually.

## API

### Stock in

```http
POST /api/stock-in
Content-Type: application/json

{
  "barcode": "1234567890",
  "product_name": "Blue Widget",
  "location": "Warehouse A",
  "quantity": 5,
  "note": "Initial count"
}
```

### Stock out

```http
POST /api/stock-out
Content-Type: application/json

{
  "barcode": "1234567890",
  "location": "Warehouse A",
  "quantity": 2,
  "note": "Customer order"
}
```

### Transfer location

```http
POST /api/transfer
Content-Type: application/json

{
  "barcode": "1234567890",
  "from_location": "Warehouse A",
  "to_location": "Storefront",
  "quantity": 1,
  "note": "Replenishment"
}
```

### Lookup scanned barcode

```http
GET /api/scan?barcode=1234567890
```

### Current stock and movement history

```http
GET /api/stock
GET /api/movements?limit=50
```

## Tests

```bash
python3 -m unittest discover -s inventory_system/tests
```

## Vercel version

The Vercel-ready app is here:

```text
inventory_system/vercel_app
```

Deploy that folder as the Vercel project root. It stores data in the browser
for now, which is good for demos and testing. For shared inventory across
devices, connect Supabase later using:

```text
inventory_system/supabase/schema.sql
```
