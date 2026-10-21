"""Always-on CSV logging for chat interactions.

This is separate from experiment logging:
- experiment_interactions.csv only records participant-backed research rows.
- user and admin mode exchanges are written to different CSV files.
"""

from __future__ import annotations

import csv
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from app.data.database import DEFAULT_DB_PATH


CHAT_LOG_DIR = DEFAULT_DB_PATH.parent / "logs"
CHAT_LOG_LOCK = threading.Lock()

CHAT_LOG_FIELDS = [
    "created_at",
    "app_mode",
    "thread_id",
    "run_id",
    "stage",
    "input_source",
    "question",
    "assistant_answer",
    "provider",
    "execution_route",
    "route_reason",
    "participant_id",
    "task_id",
    "duration_ms",
    "plan_id",
    "surface_id",
    "plan_json",
    "execution_result_json",
]


def append_chat_csv(
    *,
    thread_id: str | None,
    run_id: str | None,
    stage: str,
    input_source: str | None,
    question: str,
    assistant_answer: str | None,
    plan: dict | None = None,
    execution_result: dict | None = None,
    app_mode: str | None = None,
    participant_id: str | None = None,
    task_id: str | None = None,
    duration_ms: int | None = None,
) -> None:
    """Append one interaction row to the per-app-mode, per-input-source CSV log."""

    source = _normalize_source(input_source)
    mode = _normalize_app_mode(app_mode, participant_id)
    normalized = (execution_result or {}).get("normalized_spec") or {}
    row = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "app_mode": mode,
        "thread_id": thread_id or "",
        "run_id": run_id or "",
        "stage": stage,
        "input_source": source,
        "question": question,
        "assistant_answer": assistant_answer or "",
        "provider": (execution_result or {}).get("provider", ""),
        "execution_route": normalized.get("execution_route", ""),
        "route_reason": normalized.get("route_reason", ""),
        "participant_id": participant_id or "",
        "task_id": task_id or "",
        "duration_ms": "" if duration_ms is None else str(max(0, int(duration_ms))),
        "plan_id": (plan or {}).get("plan_id", ""),
        "surface_id": (plan or {}).get("surface_id", ""),
        "plan_json": json.dumps(plan, ensure_ascii=False) if plan is not None else "",
        "execution_result_json": json.dumps(execution_result, ensure_ascii=False) if execution_result is not None else "",
    }
    path = chat_log_path(source, mode)
    path.parent.mkdir(parents=True, exist_ok=True)
    with CHAT_LOG_LOCK:
        _ensure_header(path)
        write_header = not path.exists()
        with path.open("a", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=CHAT_LOG_FIELDS)
            if write_header:
                writer.writeheader()
            writer.writerow(row)


def chat_log_path(input_source: str | None, app_mode: str | None = None) -> Path:
    source = _normalize_source(input_source)
    source_filename = "baseline_interactions.csv" if source == "baseline" else "agent2ui_interactions.csv"
    # User-mode (participant) rows go straight into the canonical 4_3_-prefixed
    # log files instead of an unprefixed file that then needs manual merging.
    filename = f"admin_{source_filename}" if app_mode == "admin" else f"4_3_{source_filename}"
    return CHAT_LOG_DIR / filename


def _normalize_source(input_source: str | None) -> str:
    return "agent2ui" if input_source == "agent2ui" else "baseline"


def _normalize_app_mode(app_mode: str | None, participant_id: str | None) -> str:
    if app_mode in {"admin", "user"}:
        return app_mode
    return "user" if participant_id else "admin"


def _ensure_header(path: Path) -> None:
    if not path.exists():
        return
    with path.open("r", newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        existing_fields = reader.fieldnames or []
        if existing_fields == CHAT_LOG_FIELDS:
            return
        rows = list(reader)
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=CHAT_LOG_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in CHAT_LOG_FIELDS})
