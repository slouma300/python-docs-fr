import tempfile
import unittest
from pathlib import Path

from inventory_system.inventory import (
    InsufficientStockError,
    InventoryStore,
    NotFoundError,
    ValidationError,
)


class InventoryStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = InventoryStore(Path(self.temp_dir.name) / "inventory.db")
        self.store.init_db()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_stock_in_creates_product_location_and_balance(self):
        movement = self.store.stock_in(
            barcode="1234567890",
            product_name="Blue Widget",
            location="Warehouse A",
            quantity=5,
            note="initial count",
        )

        self.assertEqual(movement["movement_type"], "STOCK_IN")
        self.assertEqual(movement["to_location"], "Warehouse A")
        self.assertEqual(self.store.list_stock()[0]["quantity"], 5)

        scan = self.store.scan_barcode("1234567890")
        self.assertTrue(scan["found"])
        self.assertEqual(scan["product"]["name"], "Blue Widget")
        self.assertEqual(scan["total_quantity"], 5)

    def test_stock_out_reduces_existing_balance(self):
        self.store.stock_in(
            barcode="ABC-1",
            product_name="Cable",
            location="Shelf 1",
            quantity=10,
        )

        movement = self.store.stock_out(
            barcode="ABC-1",
            location="Shelf 1",
            quantity=4,
            note="order 100",
        )

        self.assertEqual(movement["movement_type"], "STOCK_OUT")
        self.assertEqual(movement["from_location"], "Shelf 1")
        self.assertEqual(self.store.list_stock()[0]["quantity"], 6)

    def test_stock_out_rejects_negative_stock(self):
        self.store.stock_in(
            barcode="ABC-2",
            product_name="Cable",
            location="Shelf 1",
            quantity=2,
        )

        with self.assertRaises(InsufficientStockError):
            self.store.stock_out(
                barcode="ABC-2",
                location="Shelf 1",
                quantity=3,
            )

        self.assertEqual(self.store.list_stock()[0]["quantity"], 2)

    def test_transfer_moves_stock_between_locations(self):
        self.store.stock_in(
            barcode="TRANSFER-1",
            product_name="Battery",
            location="Receiving",
            quantity=8,
        )

        movement = self.store.transfer(
            barcode="TRANSFER-1",
            from_location="Receiving",
            to_location="Storefront",
            quantity=3,
        )

        self.assertEqual(movement["movement_type"], "TRANSFER")
        self.assertEqual(movement["from_location"], "Receiving")
        self.assertEqual(movement["to_location"], "Storefront")

        stock = {
            row["location"]: row["quantity"]
            for row in self.store.list_stock()
        }
        self.assertEqual(stock["Receiving"], 5)
        self.assertEqual(stock["Storefront"], 3)

    def test_transfer_requires_different_locations(self):
        self.store.stock_in(
            barcode="SAME-LOCATION",
            product_name="Adapter",
            location="Bin A",
            quantity=1,
        )

        with self.assertRaises(ValidationError):
            self.store.transfer(
                barcode="SAME-LOCATION",
                from_location="Bin A",
                to_location="bin a",
                quantity=1,
            )

    def test_unknown_stock_out_product_is_not_found(self):
        with self.assertRaises(NotFoundError):
            self.store.stock_out(
                barcode="UNKNOWN",
                location="Warehouse A",
                quantity=1,
            )


if __name__ == "__main__":
    unittest.main()
