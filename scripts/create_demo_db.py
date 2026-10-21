"""Create a small, fully synthetic SQLite dataset without touching existing files."""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROWS = [
    ("D001", "C001", "Alpha", "delivered", "2026-10-01", 12000),
    ("D002", "C002", "Alpha", "failed", "2026-10-02", 12000),
    ("D003", "C003", "Beta", "failed", "2026-10-05", 18000),
    ("D004", "C001", "Gamma", "delivered", "2026-10-10", 24000),
    ("D005", "C002", "Alpha", "failed", "2026-10-15", 12000),
    ("D006", "C003", "Beta", "pending", "2026-10-20", 18000),
    ("D007", "C001", "Gamma", "delivered", "2026-10-20", 24000),
    ("D008", "C004", "Beta", "delivered", "2026-08-01", 18000),
]


def create_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation protects existing query DBs, including during reruns.
    with path.open("xb"):
        pass
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE orders (
            order_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL,
            product_name TEXT NOT NULL, status TEXT NOT NULL,
            created_at TEXT NOT NULL, amount INTEGER NOT NULL
        )""")
        conn.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?)", ROWS)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "Data" / "demo.sqlite")
    args = parser.parse_args()
    try:
        create_database(args.output)
    except FileExistsError:
        parser.exit(1, f"Already exists; preserved without changes: {args.output}\n")
    print(f"Created synthetic demo DB: {args.output} (8 orders, 3 failed)")


if __name__ == "__main__":
    main()
