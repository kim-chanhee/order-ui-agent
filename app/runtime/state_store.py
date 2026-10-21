"""SQLite-backed per-thread runtime state.

The FastAPI parent process and cancelable worker processes cannot share Python
module globals. This module keeps compact thread history and resolved context
in a small SQLite database so the next request can recover state even when it
runs in a different child process.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from hashlib import sha256
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.data.database import PROJECT_ROOT


MAX_THREAD_RESULTS = 10
STATE_DB_ENV = "ORDER_UI_STATE_DB_PATH"
DEFAULT_STATE_DB_PATH = PROJECT_ROOT / "Data" / "runtime_state.sqlite"
BUSY_TIMEOUT_MS = 5000
SQL_EXAMPLE_CANDIDATE_STATUS = "executed"
TRUSTED_SQL_EXAMPLE_STATUSES = frozenset({"gold_validated", "human_approved"})


def get_state_db_path() -> Path:
    """Return the configured state DB path."""

    configured = os.environ.get(STATE_DB_ENV)
    path = Path(configured).expanduser() if configured else DEFAULT_STATE_DB_PATH
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _connect() -> sqlite3.Connection:
    path = get_state_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=BUSY_TIMEOUT_MS / 1000)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA foreign_keys=ON")
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS thread_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            question TEXT NOT NULL,
            input_source TEXT,
            answer TEXT NOT NULL,
            normalized_spec_json TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_thread_results_thread_id_id
        ON thread_results(thread_id, id);

        CREATE TABLE IF NOT EXISTS thread_contexts (
            thread_id TEXT PRIMARY KEY,
            context_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS thread_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            input_source TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_thread_messages_thread_id_id
        ON thread_messages(thread_id, id);

        CREATE TABLE IF NOT EXISTS verified_sql_examples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            question TEXT NOT NULL,
            sql TEXT NOT NULL,
            tables_json TEXT NOT NULL,
            result_columns_json TEXT NOT NULL,
            schema_fingerprint TEXT NOT NULL,
            verification_status TEXT NOT NULL DEFAULT 'executed',
            verification_source TEXT NOT NULL DEFAULT 'runtime',
            plan_fingerprint TEXT NOT NULL DEFAULT '',
            UNIQUE(question, sql, schema_fingerprint)
        );

        CREATE INDEX IF NOT EXISTS idx_verified_sql_examples_schema_id
        ON verified_sql_examples(schema_fingerprint, id);

        CREATE TABLE IF NOT EXISTS plan_surfaces (
            surface_id TEXT PRIMARY KEY,
            plan_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            participant_id TEXT,
            thread_id TEXT,
            plan_json TEXT NOT NULL,
            surface_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_plan_surfaces_plan_id
        ON plan_surfaces(plan_id);
        """
    )
    # Existing state databases predate trust metadata. Keep those rows as
    # untrusted execution candidates instead of silently treating them as gold.
    _ensure_column(
        conn,
        "verified_sql_examples",
        "verification_status",
        "TEXT NOT NULL DEFAULT 'executed'",
    )
    _ensure_column(
        conn,
        "verified_sql_examples",
        "verification_source",
        "TEXT NOT NULL DEFAULT 'runtime'",
    )
    _ensure_column(
        conn,
        "verified_sql_examples",
        "plan_fingerprint",
        "TEXT NOT NULL DEFAULT ''",
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_verified_sql_examples_trust "
        "ON verified_sql_examples(schema_fingerprint, verification_status, id)"
    )


def _ensure_column(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    declaration: str,
) -> None:
    existing = {
        str(row[1])
        for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    }
    if column not in existing:
        conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {declaration}')


def record_execution_result(thread_id: str | None, question: str, execution_result: dict | None) -> None:
    """Persist a compact execution record for a chat thread."""

    if not thread_id or not execution_result:
        return
    answer = execution_result.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        return
    input_source = execution_result.get("input_source")
    normalized_spec = execution_result.get("normalized_spec") or {}
    now = _now_iso()

    with closing(_connect()) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO thread_results (
                    thread_id, created_at, question, input_source, answer, normalized_spec_json
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    thread_id,
                    now,
                    question.strip(),
                    input_source,
                    answer.strip(),
                    _json_dumps(normalized_spec),
                ),
            )
            conn.execute(
                """
                INSERT INTO thread_messages (thread_id, created_at, role, content, input_source)
                VALUES (?, ?, 'human', ?, ?)
                """,
                (thread_id, now, question.strip(), input_source),
            )
            conn.execute(
                """
                INSERT INTO thread_messages (thread_id, created_at, role, content, input_source)
                VALUES (?, ?, 'ai', ?, ?)
                """,
                (thread_id, now, answer.strip(), input_source),
            )
            conn.execute(
                """
                DELETE FROM thread_results
                WHERE thread_id = ?
                  AND id NOT IN (
                    SELECT id FROM thread_results
                    WHERE thread_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                  )
                """,
                (thread_id, thread_id, MAX_THREAD_RESULTS),
            )
            conn.execute(
                """
                DELETE FROM thread_messages
                WHERE thread_id = ?
                  AND id NOT IN (
                    SELECT id FROM thread_messages
                    WHERE thread_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                  )
                """,
                (thread_id, thread_id, MAX_THREAD_RESULTS * 2),
            )
            _record_verified_sql_example(conn, question, execution_result)


def get_thread_results(thread_id: str | None) -> list[dict]:
    """Return stored execution records in chronological order."""

    if not thread_id:
        return []
    with closing(_connect()) as conn:
        rows = conn.execute(
            """
            SELECT question, input_source, answer, normalized_spec_json
            FROM (
                SELECT *
                FROM thread_results
                WHERE thread_id = ?
                ORDER BY id DESC
                LIMIT ?
            )
            ORDER BY id ASC
            """,
            (thread_id, MAX_THREAD_RESULTS),
        ).fetchall()
    return [
        {
            "question": row["question"],
            "input_source": row["input_source"],
            "answer": row["answer"],
            "normalized_spec": _json_loads(row["normalized_spec_json"], {}),
        }
        for row in rows
    ]


def _record_verified_sql_example(
    conn: sqlite3.Connection,
    question: str,
    execution_result: dict,
) -> None:
    """Persist an execution candidate without granting it semantic trust."""

    normalized = execution_result.get("normalized_spec") or {}
    execution = normalized.get("analysis_execution") or {}
    metadata = execution.get("metadata") or {}
    sql = execution.get("sql")
    if not (
        isinstance(sql, str)
        and sql.strip()
        and metadata.get("validation_passed") is True
        and metadata.get("memory_eligible") is True
    ):
        return
    try:
        from app.execution.sql_tools import extract_referenced_tables

        tables = sorted(extract_referenced_tables(sql))
    except Exception:
        tables = sorted(str(table) for table in metadata.get("schema_tables") or [])
    fingerprint = str(metadata.get("schema_fingerprint") or "")
    if not fingerprint:
        return
    requested_status = str(
        metadata.get("example_verification_status") or SQL_EXAMPLE_CANDIDATE_STATUS
    )
    status = (
        requested_status
        if requested_status in TRUSTED_SQL_EXAMPLE_STATUSES
        else SQL_EXAMPLE_CANDIDATE_STATUS
    )
    source = str(metadata.get("example_verification_source") or "runtime")[:100]
    plan_fingerprint = _analysis_plan_fingerprint(normalized)
    conn.execute(
        """
        INSERT INTO verified_sql_examples (
            created_at, question, sql, tables_json, result_columns_json,
            schema_fingerprint, verification_status, verification_source,
            plan_fingerprint
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(question, sql, schema_fingerprint) DO UPDATE SET
            created_at = excluded.created_at,
            tables_json = excluded.tables_json,
            result_columns_json = excluded.result_columns_json,
            verification_status = CASE
                WHEN verified_sql_examples.verification_status IN ('gold_validated', 'human_approved')
                THEN verified_sql_examples.verification_status
                ELSE excluded.verification_status
            END,
            verification_source = CASE
                WHEN verified_sql_examples.verification_status IN ('gold_validated', 'human_approved')
                THEN verified_sql_examples.verification_source
                ELSE excluded.verification_source
            END,
            plan_fingerprint = excluded.plan_fingerprint
        """,
        (
            _now_iso(),
            question.strip(),
            sql.strip(),
            _json_dumps(tables),
            _json_dumps(execution.get("columns") or []),
            fingerprint,
            status,
            source,
            plan_fingerprint,
        ),
    )


def _analysis_plan_fingerprint(normalized_spec: dict[str, Any]) -> str:
    plan = normalized_spec.get("analysis_plan")
    if not isinstance(plan, dict):
        confirmed = normalized_spec.get("confirmed_context") or {}
        plan = confirmed.get("confirmed_plan") if isinstance(confirmed, dict) else None
    if not isinstance(plan, dict):
        return ""
    payload = json.dumps(
        plan,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(payload.encode("utf-8")).hexdigest()[:16]


def set_sql_example_verification(
    *,
    question: str,
    sql: str,
    schema_fingerprint: str,
    status: str,
    source: str,
) -> bool:
    """Promote one exact SQL example only through an explicit trusted action."""

    if status not in TRUSTED_SQL_EXAMPLE_STATUSES:
        raise ValueError(
            "verification status must be one of: "
            + ", ".join(sorted(TRUSTED_SQL_EXAMPLE_STATUSES))
        )
    if not source.strip():
        raise ValueError("verification source is required")
    with closing(_connect()) as conn:
        with conn:
            cursor = conn.execute(
                """
                UPDATE verified_sql_examples
                SET verification_status = ?, verification_source = ?, created_at = ?
                WHERE question = ? AND sql = ? AND schema_fingerprint = ?
                """,
                (
                    status,
                    source.strip()[:100],
                    _now_iso(),
                    question.strip(),
                    sql.strip(),
                    schema_fingerprint,
                ),
            )
    return cursor.rowcount == 1


def get_similar_sql_examples(
    question: str,
    *,
    schema_fingerprint: str,
    limit: int = 3,
) -> list[dict]:
    """Return only explicitly trusted examples for the current schema version."""

    if not question.strip() or not schema_fingerprint or limit <= 0:
        return []
    with closing(_connect()) as conn:
        rows = conn.execute(
            """
            SELECT question, sql, tables_json, result_columns_json
            FROM verified_sql_examples
            WHERE schema_fingerprint = ?
              AND verification_status IN ('gold_validated', 'human_approved')
            ORDER BY id DESC
            LIMIT 200
            """,
            (schema_fingerprint,),
        ).fetchall()
    query_terms = _memory_terms(question)
    scored: list[tuple[float, sqlite3.Row]] = []
    for row in rows:
        example_terms = _memory_terms(str(row["question"]))
        exact = len(query_terms & example_terms)
        partial = sum(
            1
            for term in query_terms - example_terms
            if len(term) >= 2
            and any(term in candidate or candidate in term for candidate in example_terms)
        )
        score = exact * 3.0 + partial
        if str(row["question"]).strip().lower() == question.strip().lower():
            score += 20.0
        if score > 0:
            scored.append((score, row))
    scored.sort(key=lambda item: -item[0])
    return [
        {
            "question": row["question"],
            "sql": row["sql"],
            "tables": _json_loads(row["tables_json"], []),
            "result_columns": _json_loads(row["result_columns_json"], []),
        }
        for _score, row in scored[:limit]
    ]


def _memory_terms(text: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z0-9_]+|[가-힣]{2,}", text.replace("_", " "))
        if len(token) >= 2
    }


def update_thread_context(thread_id: str | None, values: dict | None) -> None:
    """Merge resolved execution context for later turns."""

    if not thread_id or not values:
        return
    cleaned = {key: value for key, value in values.items() if value not in (None, "", [])}
    if not cleaned:
        return
    with closing(_connect()) as conn:
        with conn:
            row = conn.execute(
                "SELECT context_json FROM thread_contexts WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
            context = _json_loads(row["context_json"] if row else None, {})
            if not isinstance(context, dict):
                context = {}
            context.update(cleaned)
            conn.execute(
                """
                INSERT INTO thread_contexts (thread_id, context_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET
                    context_json = excluded.context_json,
                    updated_at = excluded.updated_at
                """,
                (thread_id, _json_dumps(context), _now_iso()),
            )


def get_thread_context(thread_id: str | None) -> dict:
    """실행 메타데이터와 모드별 최근 문답을 포함한 대화 상태를 읽는다."""

    if not thread_id:
        return {}
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT context_json FROM thread_contexts WHERE thread_id = ?", (thread_id,)
        ).fetchone()
    context = _json_loads(row["context_json"] if row else None, {})
    return context if isinstance(context, dict) else {}
