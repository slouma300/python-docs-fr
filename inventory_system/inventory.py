"""Inventory persistence and stock movement rules.

The module intentionally uses only Python's standard library so the app can be
run from this repository without installing a web framework.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional


class InventoryError(Exception):
    """Base class for inventory validation errors."""


class ValidationError(InventoryError):
    """Raised when user input is invalid."""


class NotFoundError(InventoryError):
    """Raised when a referenced product or location does not exist."""


class InsufficientStockError(InventoryError):
    """Raised when a stock-out or transfer would make stock negative."""


class InventoryStore:
    """SQLite-backed inventory store."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    barcode TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    sku TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS locations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS stock_levels (
                    product_id INTEGER NOT NULL,
                    location_id INTEGER NOT NULL,
                    quantity INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
                    PRIMARY KEY (product_id, location_id),
                    FOREIGN KEY (product_id) REFERENCES products(id),
                    FOREIGN KEY (location_id) REFERENCES locations(id)
                );

                CREATE TABLE IF NOT EXISTS stock_movements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    movement_type TEXT NOT NULL CHECK (
                        movement_type IN ('STOCK_IN', 'STOCK_OUT', 'TRANSFER')
                    ),
                    product_id INTEGER NOT NULL,
                    from_location_id INTEGER,
                    to_location_id INTEGER,
                    quantity INTEGER NOT NULL CHECK (quantity > 0),
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (product_id) REFERENCES products(id),
                    FOREIGN KEY (from_location_id) REFERENCES locations(id),
                    FOREIGN KEY (to_location_id) REFERENCES locations(id)
                );

                CREATE INDEX IF NOT EXISTS idx_stock_movements_created_at
                    ON stock_movements(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_products_barcode
                    ON products(barcode);
                """
            )

    def stock_in(
        self,
        *,
        barcode: str,
        product_name: Optional[str],
        location: str,
        quantity: Any,
        note: str = "",
    ) -> Dict[str, Any]:
        barcode = self._clean_required(barcode, "barcode")
        location = self._clean_required(location, "location")
        qty = self._quantity(quantity)
        product_name = self._clean_optional(product_name) or f"Item {barcode}"
        note = self._clean_optional(note)

        with self._transaction() as conn:
            product_id = self._ensure_product(conn, barcode, product_name)
            location_id = self._ensure_location(conn, location)
            self._increase_stock(conn, product_id, location_id, qty)
            movement_id = self._record_movement(
                conn,
                movement_type="STOCK_IN",
                product_id=product_id,
                from_location_id=None,
                to_location_id=location_id,
                quantity=qty,
                note=note,
            )
            return self.get_movement(movement_id, conn=conn)

    def stock_out(
        self,
        *,
        barcode: str,
        location: str,
        quantity: Any,
        note: str = "",
    ) -> Dict[str, Any]:
        barcode = self._clean_required(barcode, "barcode")
        location = self._clean_required(location, "location")
        qty = self._quantity(quantity)
        note = self._clean_optional(note)

        with self._transaction() as conn:
            product_id = self._get_product_id(conn, barcode)
            location_id = self._get_location_id(conn, location)
            self._decrease_stock(conn, product_id, location_id, qty)
            movement_id = self._record_movement(
                conn,
                movement_type="STOCK_OUT",
                product_id=product_id,
                from_location_id=location_id,
                to_location_id=None,
                quantity=qty,
                note=note,
            )
            return self.get_movement(movement_id, conn=conn)

    def transfer(
        self,
        *,
        barcode: str,
        from_location: str,
        to_location: str,
        quantity: Any,
        note: str = "",
    ) -> Dict[str, Any]:
        barcode = self._clean_required(barcode, "barcode")
        from_location = self._clean_required(from_location, "from_location")
        to_location = self._clean_required(to_location, "to_location")
        if from_location.casefold() == to_location.casefold():
            raise ValidationError("Source and destination locations must differ")
        qty = self._quantity(quantity)
        note = self._clean_optional(note)

        with self._transaction() as conn:
            product_id = self._get_product_id(conn, barcode)
            from_location_id = self._get_location_id(conn, from_location)
            to_location_id = self._ensure_location(conn, to_location)
            self._decrease_stock(conn, product_id, from_location_id, qty)
            self._increase_stock(conn, product_id, to_location_id, qty)
            movement_id = self._record_movement(
                conn,
                movement_type="TRANSFER",
                product_id=product_id,
                from_location_id=from_location_id,
                to_location_id=to_location_id,
                quantity=qty,
                note=note,
            )
            return self.get_movement(movement_id, conn=conn)

    def scan_barcode(self, barcode: str) -> Dict[str, Any]:
        barcode = self._clean_required(barcode, "barcode")
        with self._connect() as conn:
            product = conn.execute(
                "SELECT id, barcode, name, sku FROM products WHERE barcode = ?",
                (barcode,),
            ).fetchone()
            if product is None:
                return {
                    "found": False,
                    "barcode": barcode,
                    "product": None,
                    "locations": [],
                    "total_quantity": 0,
                }

            locations = conn.execute(
                """
                SELECT locations.name AS location, stock_levels.quantity
                FROM stock_levels
                JOIN locations ON locations.id = stock_levels.location_id
                WHERE stock_levels.product_id = ?
                  AND stock_levels.quantity > 0
                ORDER BY locations.name
                """,
                (product["id"],),
            ).fetchall()
            total = sum(row["quantity"] for row in locations)
            return {
                "found": True,
                "barcode": barcode,
                "product": self._product_dict(product),
                "locations": [dict(row) for row in locations],
                "total_quantity": total,
            }

    def list_stock(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    products.barcode,
                    products.name AS product_name,
                    locations.name AS location,
                    stock_levels.quantity
                FROM stock_levels
                JOIN products ON products.id = stock_levels.product_id
                JOIN locations ON locations.id = stock_levels.location_id
                WHERE stock_levels.quantity > 0
                ORDER BY products.name, locations.name
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def list_movements(self, limit: Any = 50) -> List[Dict[str, Any]]:
        limit = self._limit(limit)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    stock_movements.id,
                    stock_movements.movement_type,
                    products.barcode,
                    products.name AS product_name,
                    from_locations.name AS from_location,
                    to_locations.name AS to_location,
                    stock_movements.quantity,
                    stock_movements.note,
                    stock_movements.created_at
                FROM stock_movements
                JOIN products ON products.id = stock_movements.product_id
                LEFT JOIN locations AS from_locations
                    ON from_locations.id = stock_movements.from_location_id
                LEFT JOIN locations AS to_locations
                    ON to_locations.id = stock_movements.to_location_id
                ORDER BY stock_movements.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_movement(
        self, movement_id: int, *, conn: Optional[sqlite3.Connection] = None
    ) -> Dict[str, Any]:
        connection_owner = conn is None
        if conn is None:
            conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT
                    stock_movements.id,
                    stock_movements.movement_type,
                    products.barcode,
                    products.name AS product_name,
                    from_locations.name AS from_location,
                    to_locations.name AS to_location,
                    stock_movements.quantity,
                    stock_movements.note,
                    stock_movements.created_at
                FROM stock_movements
                JOIN products ON products.id = stock_movements.product_id
                LEFT JOIN locations AS from_locations
                    ON from_locations.id = stock_movements.from_location_id
                LEFT JOIN locations AS to_locations
                    ON to_locations.id = stock_movements.to_location_id
                WHERE stock_movements.id = ?
                """,
                (movement_id,),
            ).fetchone()
            if row is None:
                raise NotFoundError(f"Movement {movement_id} was not found")
            return dict(row)
        finally:
            if connection_owner:
                conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_product(
        self, conn: sqlite3.Connection, barcode: str, product_name: str
    ) -> int:
        existing = conn.execute(
            "SELECT id, name FROM products WHERE barcode = ?", (barcode,)
        ).fetchone()
        if existing is not None:
            if product_name and product_name != existing["name"]:
                conn.execute(
                    "UPDATE products SET name = ? WHERE id = ?",
                    (product_name, existing["id"]),
                )
            return int(existing["id"])

        cursor = conn.execute(
            "INSERT INTO products (barcode, name) VALUES (?, ?)",
            (barcode, product_name),
        )
        return int(cursor.lastrowid)

    def _ensure_location(self, conn: sqlite3.Connection, name: str) -> int:
        existing = conn.execute(
            "SELECT id FROM locations WHERE name = ?", (name,)
        ).fetchone()
        if existing is not None:
            return int(existing["id"])

        cursor = conn.execute("INSERT INTO locations (name) VALUES (?)", (name,))
        return int(cursor.lastrowid)

    def _get_product_id(self, conn: sqlite3.Connection, barcode: str) -> int:
        row = conn.execute(
            "SELECT id FROM products WHERE barcode = ?", (barcode,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"No product found for barcode {barcode}")
        return int(row["id"])

    def _get_location_id(self, conn: sqlite3.Connection, name: str) -> int:
        row = conn.execute("SELECT id FROM locations WHERE name = ?", (name,)).fetchone()
        if row is None:
            raise NotFoundError(f"Location {name} was not found")
        return int(row["id"])

    def _increase_stock(
        self, conn: sqlite3.Connection, product_id: int, location_id: int, quantity: int
    ) -> None:
        conn.execute(
            """
            INSERT INTO stock_levels (product_id, location_id, quantity)
            VALUES (?, ?, ?)
            ON CONFLICT(product_id, location_id)
            DO UPDATE SET quantity = quantity + excluded.quantity
            """,
            (product_id, location_id, quantity),
        )

    def _decrease_stock(
        self, conn: sqlite3.Connection, product_id: int, location_id: int, quantity: int
    ) -> None:
        current = conn.execute(
            """
            SELECT quantity
            FROM stock_levels
            WHERE product_id = ? AND location_id = ?
            """,
            (product_id, location_id),
        ).fetchone()
        current_qty = int(current["quantity"]) if current is not None else 0
        if current_qty < quantity:
            raise InsufficientStockError(
                f"Only {current_qty} units available at this location"
            )

        conn.execute(
            """
            UPDATE stock_levels
            SET quantity = quantity - ?
            WHERE product_id = ? AND location_id = ?
            """,
            (quantity, product_id, location_id),
        )

    def _record_movement(
        self,
        conn: sqlite3.Connection,
        *,
        movement_type: str,
        product_id: int,
        from_location_id: Optional[int],
        to_location_id: Optional[int],
        quantity: int,
        note: str,
    ) -> int:
        cursor = conn.execute(
            """
            INSERT INTO stock_movements (
                movement_type,
                product_id,
                from_location_id,
                to_location_id,
                quantity,
                note
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                movement_type,
                product_id,
                from_location_id,
                to_location_id,
                quantity,
                note,
            ),
        )
        return int(cursor.lastrowid)

    @staticmethod
    def _clean_required(value: Any, field_name: str) -> str:
        cleaned = InventoryStore._clean_optional(value)
        if not cleaned:
            raise ValidationError(f"{field_name} is required")
        return cleaned

    @staticmethod
    def _clean_optional(value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @staticmethod
    def _quantity(value: Any) -> int:
        try:
            quantity = int(value)
        except (TypeError, ValueError):
            raise ValidationError("quantity must be a whole number")
        if quantity <= 0:
            raise ValidationError("quantity must be greater than zero")
        return quantity

    @staticmethod
    def _limit(value: Any) -> int:
        try:
            limit = int(value)
        except (TypeError, ValueError):
            return 50
        return min(max(limit, 1), 500)

    @staticmethod
    def _product_dict(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "barcode": row["barcode"],
            "name": row["name"],
            "sku": row["sku"],
        }
