"""Small HTTP server for the standalone inventory system."""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    from .inventory import (
        InsufficientStockError,
        InventoryError,
        InventoryStore,
        NotFoundError,
        ValidationError,
    )
except ImportError:  # pragma: no cover - supports `python inventory_system/app.py`
    from inventory import (  # type: ignore
        InsufficientStockError,
        InventoryError,
        InventoryStore,
        NotFoundError,
        ValidationError,
    )


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DEFAULT_DB = BASE_DIR / "inventory.db"


class InventoryRequestHandler(BaseHTTPRequestHandler):
    store: InventoryStore

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self._json({"ok": True})
        elif parsed.path == "/api/stock":
            self._json({"stock": self.store.list_stock()})
        elif parsed.path == "/api/movements":
            limit = parse_qs(parsed.query).get("limit", [50])[0]
            self._json({"movements": self.store.list_movements(limit)})
        elif parsed.path == "/api/scan":
            barcode = parse_qs(parsed.query).get("barcode", [""])[0]
            self._json(self.store.scan_barcode(barcode))
        else:
            self._serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            payload = self._read_json()
            if parsed.path == "/api/stock-in":
                result = self.store.stock_in(
                    barcode=payload.get("barcode"),
                    product_name=payload.get("product_name"),
                    location=payload.get("location"),
                    quantity=payload.get("quantity"),
                    note=payload.get("note", ""),
                )
            elif parsed.path == "/api/stock-out":
                result = self.store.stock_out(
                    barcode=payload.get("barcode"),
                    location=payload.get("location"),
                    quantity=payload.get("quantity"),
                    note=payload.get("note", ""),
                )
            elif parsed.path == "/api/transfer":
                result = self.store.transfer(
                    barcode=payload.get("barcode"),
                    from_location=payload.get("from_location"),
                    to_location=payload.get("to_location"),
                    quantity=payload.get("quantity"),
                    note=payload.get("note", ""),
                )
            elif parsed.path == "/api/scan":
                result = self.store.scan_barcode(payload.get("barcode"))
            else:
                self._json({"error": "Not found"}, status=404)
                return
            self._json({"movement": result})
        except json.JSONDecodeError:
            self._json({"error": "Request body must be valid JSON"}, status=400)
        except ValidationError as exc:
            self._json({"error": str(exc)}, status=400)
        except NotFoundError as exc:
            self._json({"error": str(exc)}, status=404)
        except InsufficientStockError as exc:
            self._json({"error": str(exc)}, status=409)
        except InventoryError as exc:
            self._json({"error": str(exc)}, status=400)

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write(
            "%s - - [%s] %s\n"
            % (self.client_address[0], self.log_date_time_string(), format % args)
        )

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def _json(self, payload: dict, *, status: int = 200) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, request_path: str) -> None:
        path = "/index.html" if request_path in ("", "/") else request_path
        safe_parts = [part for part in path.split("/") if part and part not in (".", "..")]
        file_path = STATIC_DIR.joinpath(*safe_parts)
        if not file_path.is_file():
            self._json({"error": "Not found"}, status=404)
            return

        body = file_path.read_bytes()
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def build_server(host: str, port: int, db_path: Path) -> ThreadingHTTPServer:
    store = InventoryStore(db_path)
    store.init_db()
    InventoryRequestHandler.store = store
    return ThreadingHTTPServer((host, port), InventoryRequestHandler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the inventory system server.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help="SQLite database path",
    )
    args = parser.parse_args()

    server = build_server(args.host, args.port, args.db)
    print(f"Inventory system running at http://{args.host}:{args.port}")
    print(f"Using database: {args.db}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping inventory system")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
