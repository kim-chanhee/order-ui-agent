"""Database location and generic SQLite schema inspection helpers."""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _resolve_default_database_path() -> Path:
    configured = os.environ.get("ORDER_UI_DB_PATH")
    if configured:
        return Path(configured).expanduser()

    data_dir = PROJECT_ROOT / "Data"
    conventional = data_dir / "database.sqlite"
    if conventional.is_file():
        return conventional

    state_path = Path(
        os.environ.get("ORDER_UI_STATE_DB_PATH", data_dir / "runtime_state.sqlite")
    ).expanduser()
    candidates = [
        path for path in data_dir.glob("*.sqlite")
        if path.is_file() and path.resolve() != state_path.resolve()
    ]
    if candidates:
        return max(candidates, key=lambda path: path.stat().st_size)
    return conventional


DEFAULT_DB_PATH = _resolve_default_database_path()


def ensure_database_ready(db_path: str | Path | None = None) -> None:
    """Fail early when the configured SQLite database cannot be read."""

    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"SQLite database not found: {path.name}")
    with closing(sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)) as conn:
        conn.execute("SELECT 1").fetchone()


