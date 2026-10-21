"""SQLite-backed experiment session and interaction state."""

from __future__ import annotations

import csv
import io
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from app.experiment.tasks import score_plan_semantics, score_result_accuracy, task_complexity, task_ids
from app.runtime.state_store import BUSY_TIMEOUT_MS, get_state_db_path


Condition = Literal["baseline", "agent2ui"]
SESSION_STEPS = [
    "consent",
    "condition_1_task_1",
    "condition_1_task_2",
    "condition_1_survey",
    "condition_2_task_1",
    "condition_2_task_2",
    "condition_2_survey",
    "comparison_survey",
    "completed",
]
INTERACTION_FIELDS = [
    "interaction_id",
    "run_id",
    "participant_id",
    "assignment_group",
    "condition",
    "condition_order",
    "task_id",
    "task_complexity",
    "thread_id",
    "attempt_number",
    "question",
    "draft_plan_json",
    "confirmed_plan_json",
    "planner_source",
    "planner_confidence",
    "changed_fields_json",
    "plan_diff_json",
    "clarification_count",
    "execution_route",
    "execution_success",
    "error_type",
    "started_at",
    "plan_created_at",
    "confirmed_at",
    "completed_at",
    "planning_duration_ms",
    "editing_duration_ms",
    "execution_duration_ms",
    "total_duration_ms",
    "result_row_count",
    "plan_semantic_match",
    "result_accuracy",
]


@dataclass(frozen=True)
class ExperimentSession:
    participant_id: str
    assignment_group: str
    condition_order: list[Condition]
    current_condition: Condition | None
    current_task_id: str | None
    current_step: str
    started_at: str
    completed_at: str | None
    status: str

    def model_dump(self) -> dict[str, Any]:
        return {
            "participant_id": self.participant_id,
            "assignment_group": self.assignment_group,
            "condition_order": list(self.condition_order),
            "current_condition": self.current_condition,
            "current_task_id": self.current_task_id,
            "current_step": self.current_step,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "status": self.status,
            "progress": {"index": SESSION_STEPS.index(self.current_step), "total": len(SESSION_STEPS) - 1},
        }


def start_session(participant_id: str) -> ExperimentSession:
    """Create or return a stable experiment session for a participant."""

    with closing(_connect()) as conn:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = _fetch_session(conn, participant_id)
            if existing:
                return existing
            group = _next_assignment_group(conn)
            order = ["baseline", "agent2ui"] if group == "A" else ["agent2ui", "baseline"]
            now = _now_iso()
            conn.execute(
                """
                INSERT INTO experiment_sessions (
                    participant_id, assignment_group, condition_order_json, current_condition,
                    current_task_id, current_step, started_at, completed_at, status
                )
                VALUES (?, ?, ?, ?, ?, 'consent', ?, NULL, 'active')
                """,
                (participant_id, group, _json_dumps(order), None, None, now),
            )
            return _fetch_session(conn, participant_id)  # type: ignore[return-value]


def get_session(participant_id: str) -> ExperimentSession | None:
    with closing(_connect()) as conn:
        return _fetch_session(conn, participant_id)


def require_session(participant_id: str | None) -> ExperimentSession | None:
    if not participant_id:
        return None
    return get_session(participant_id)


def experiment_thread_id(participant_id: str, condition: str, task_id: str) -> str:
    return f"{participant_id}-{condition}-{task_id}"


def validate_active_task(session: ExperimentSession, input_source: str) -> tuple[str, str]:
    """Validate current step and return canonical condition/task thread fields."""

    if session.status == "completed" or session.current_step == "completed":
        raise ValueError("experiment session is already completed")
    if not session.current_step.startswith("condition_") or "_task_" not in session.current_step:
        raise ValueError("current experiment step does not allow task input")
    expected_source = "agent2ui" if session.current_condition == "agent2ui" else "baseline"
    if input_source != expected_source:
        raise ValueError("input_source is not allowed for the current experiment condition")
    if not session.current_condition or not session.current_task_id:
        raise ValueError("experiment session has no active task")
    return session.current_condition, session.current_task_id


def complete_current_task(participant_id: str) -> ExperimentSession:
    with closing(_connect()) as conn:
        with conn:
            session = _require_session_in_conn(conn, participant_id)
            condition, task_id = validate_active_task(session, "agent2ui" if session.current_condition == "agent2ui" else "baseline")
            if not _has_successful_interaction(conn, participant_id, condition, task_id):
                raise ValueError("current task cannot be completed before a successful interaction is recorded")
            conn.execute(
                """
                INSERT INTO experiment_task_completions (participant_id, step, condition, task_id, completed_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(participant_id, step) DO UPDATE SET completed_at = excluded.completed_at
                """,
                (participant_id, session.current_step, condition, task_id, _now_iso()),
            )
            return _fetch_session(conn, participant_id)  # type: ignore[return-value]


def advance_step(participant_id: str) -> ExperimentSession:
    with closing(_connect()) as conn:
        with conn:
            session = _require_session_in_conn(conn, participant_id)
            if session.current_step == "completed":
                return session
            if session.current_step.startswith("condition_") and "_task_" in session.current_step:
                row = conn.execute(
                    "SELECT 1 FROM experiment_task_completions WHERE participant_id = ? AND step = ?",
                    (participant_id, session.current_step),
                ).fetchone()
                if not row:
                    raise ValueError("complete the current task before advancing")
            next_step = SESSION_STEPS[SESSION_STEPS.index(session.current_step) + 1]
            condition, task = _condition_task_for_step(session.condition_order, next_step)
            completed_at = _now_iso() if next_step == "completed" else None
            status = "completed" if next_step == "completed" else "active"
            conn.execute(
                """
                UPDATE experiment_sessions
                SET current_step = ?, current_condition = ?, current_task_id = ?,
                    completed_at = COALESCE(?, completed_at), status = ?
                WHERE participant_id = ?
                """,
                (next_step, condition, task, completed_at, status, participant_id),
            )
            return _fetch_session(conn, participant_id)  # type: ignore[return-value]


def record_interaction(fields: dict[str, Any]) -> None:
    """Insert an experiment interaction once, keyed by interaction_id/run_id."""

    participant_id = fields.get("participant_id")
    if not participant_id:
        return
    session = get_session(str(participant_id))
    if not session:
        return
    condition = fields.get("condition") or session.current_condition
    task_id = fields.get("task_id") or session.current_task_id
    analysis_payload = fields.get("analysis_payload") or {}
    plan = fields.get("confirmed_plan") or fields.get("draft_plan")
    result_rows = analysis_payload.get("rows") if isinstance(analysis_payload, dict) else []
    row = {
        "interaction_id": fields.get("interaction_id") or fields.get("run_id") or f"{participant_id}-{_now_iso()}",
        "run_id": fields.get("run_id") or None,
        "participant_id": participant_id,
        "assignment_group": session.assignment_group,
        "condition": condition or "",
        "condition_order": "->".join(session.condition_order),
        "task_id": task_id or "",
        "task_complexity": task_complexity(str(task_id)),
        "thread_id": fields.get("thread_id") or "",
        "attempt_number": None,
        "question": fields.get("question") or "",
        "draft_plan_json": _json_dumps(fields.get("draft_plan")) if fields.get("draft_plan") is not None else "",
        "confirmed_plan_json": _json_dumps(fields.get("confirmed_plan")) if fields.get("confirmed_plan") is not None else "",
        "planner_source": fields.get("planner_source") or "",
        "planner_confidence": _string_or_empty(fields.get("planner_confidence")),
        "changed_fields_json": _json_dumps(fields.get("changed_fields") or []),
        "plan_diff_json": _json_dumps(fields.get("plan_diff") or []),
        "clarification_count": int(fields.get("clarification_count") or 0),
        "execution_route": fields.get("execution_route") or "",
        "execution_success": 1 if fields.get("execution_success") else 0,
        "error_type": fields.get("error_type") or "",
        "started_at": fields.get("started_at") or "",
        "plan_created_at": fields.get("plan_created_at") or "",
        "confirmed_at": fields.get("confirmed_at") or "",
        "completed_at": fields.get("completed_at") or "",
        "planning_duration_ms": _nonnegative_int(fields.get("planning_duration_ms")),
        "editing_duration_ms": _nonnegative_int(fields.get("editing_duration_ms")),
        "execution_duration_ms": _nonnegative_int(fields.get("execution_duration_ms")),
        "total_duration_ms": _nonnegative_int(fields.get("total_duration_ms")),
        "result_row_count": len(result_rows) if isinstance(result_rows, list) else 0,
        "plan_semantic_match": _bool_to_db(score_plan_semantics(plan, str(task_id))),
        "result_accuracy": _bool_to_db(score_result_accuracy(analysis_payload, str(task_id))),
    }
    with closing(_connect()) as conn:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            row["attempt_number"] = _next_attempt_number(conn, str(participant_id), str(condition), str(task_id))
            conn.execute(
                f"""
                INSERT OR IGNORE INTO experiment_interaction_logs ({', '.join(INTERACTION_FIELDS)})
                VALUES ({', '.join('?' for _ in INTERACTION_FIELDS)})
                """,
                [row[field] for field in INTERACTION_FIELDS],
            )


def export_interactions_csv() -> str:
    with closing(_connect()) as conn:
        rows = conn.execute(
            f"SELECT {', '.join(INTERACTION_FIELDS)} FROM experiment_interaction_logs ORDER BY started_at, interaction_id"
        ).fetchall()
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=INTERACTION_FIELDS)
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row[field] for field in INTERACTION_FIELDS})
    return output.getvalue()


def _connect() -> sqlite3.Connection:
    path = get_state_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=BUSY_TIMEOUT_MS / 1000)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS experiment_sessions (
            participant_id TEXT PRIMARY KEY,
            assignment_group TEXT NOT NULL,
            condition_order_json TEXT NOT NULL,
            current_condition TEXT,
            current_task_id TEXT,
            current_step TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            status TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS experiment_task_completions (
            participant_id TEXT NOT NULL,
            step TEXT NOT NULL,
            condition TEXT NOT NULL,
            task_id TEXT NOT NULL,
            completed_at TEXT NOT NULL,
            PRIMARY KEY (participant_id, step)
        );

        CREATE TABLE IF NOT EXISTS experiment_interaction_logs (
            interaction_id TEXT PRIMARY KEY,
            run_id TEXT UNIQUE,
            participant_id TEXT NOT NULL,
            assignment_group TEXT NOT NULL,
            condition TEXT NOT NULL,
            condition_order TEXT NOT NULL,
            task_id TEXT NOT NULL,
            task_complexity TEXT,
            thread_id TEXT NOT NULL,
            attempt_number INTEGER NOT NULL,
            question TEXT NOT NULL,
            draft_plan_json TEXT,
            confirmed_plan_json TEXT,
            planner_source TEXT,
            planner_confidence TEXT,
            changed_fields_json TEXT,
            plan_diff_json TEXT,
            clarification_count INTEGER,
            execution_route TEXT,
            execution_success INTEGER,
            error_type TEXT,
            started_at TEXT,
            plan_created_at TEXT,
            confirmed_at TEXT,
            completed_at TEXT,
            planning_duration_ms INTEGER,
            editing_duration_ms INTEGER,
            execution_duration_ms INTEGER,
            total_duration_ms INTEGER,
            result_row_count INTEGER,
            plan_semantic_match INTEGER,
            result_accuracy INTEGER
        );
        """
    )


def _fetch_session(conn: sqlite3.Connection, participant_id: str) -> ExperimentSession | None:
    row = conn.execute(
        """
        SELECT participant_id, assignment_group, condition_order_json, current_condition, current_task_id,
               current_step, started_at, completed_at, status
        FROM experiment_sessions
        WHERE participant_id = ?
        """,
        (participant_id,),
    ).fetchone()
    if not row:
        return None
    return ExperimentSession(
        participant_id=row["participant_id"],
        assignment_group=row["assignment_group"],
        condition_order=list(json.loads(row["condition_order_json"])),
        current_condition=row["current_condition"],
        current_task_id=row["current_task_id"],
        current_step=row["current_step"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        status=row["status"],
    )


def _require_session_in_conn(conn: sqlite3.Connection, participant_id: str) -> ExperimentSession:
    session = _fetch_session(conn, participant_id)
    if not session:
        raise ValueError("experiment session not found")
    return session


def _next_assignment_group(conn: sqlite3.Connection) -> str:
    rows = conn.execute("SELECT assignment_group, COUNT(*) AS count FROM experiment_sessions GROUP BY assignment_group").fetchall()
    counts = {row["assignment_group"]: row["count"] for row in rows}
    return "A" if counts.get("A", 0) <= counts.get("B", 0) else "B"


def _condition_task_for_step(order: list[Condition], step: str) -> tuple[Condition | None, str | None]:
    if not step.startswith("condition_"):
        return None, None
    condition_index = 0 if step.startswith("condition_1") else 1
    condition = order[condition_index]
    if "_task_1" in step:
        return condition, task_ids()[0]
    if "_task_2" in step:
        return condition, task_ids()[1]
    return condition, None


def _has_successful_interaction(conn: sqlite3.Connection, participant_id: str, condition: str, task_id: str) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM experiment_interaction_logs
        WHERE participant_id = ? AND condition = ? AND task_id = ? AND execution_success = 1
        LIMIT 1
        """,
        (participant_id, condition, task_id),
    ).fetchone()
    return bool(row)


def _next_attempt_number(conn: sqlite3.Connection, participant_id: str, condition: str, task_id: str) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(MAX(attempt_number), 0) AS last_attempt
        FROM experiment_interaction_logs
        WHERE participant_id = ? AND condition = ? AND task_id = ?
        """,
        (participant_id, condition, task_id),
    ).fetchone()
    return int(row["last_attempt"] or 0) + 1


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _string_or_empty(value: Any) -> str:
    return "" if value is None else str(value)


def _nonnegative_int(value: Any) -> int:
    if value in (None, ""):
        return 0
    return max(0, int(value))


def _bool_to_db(value: bool | None) -> int | None:
    if value is None:
        return None
    return 1 if value else 0
