"""앱 기동 시 로컬 자원이 쓸 수 있는지 검사한다.

DB·상태 저장소·스키마·실험 설정·AGENT_PROVIDER를 확인하고,
실패하면 `StartupCheckError`를 올린다. 경로·비밀은 응답에 넣지 않는다.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from app.core.llm_settings import resolve_agent_llm_settings
from app.data.database import DEFAULT_DB_PATH, ensure_database_ready
from app.experiment.tasks import load_task_config
from app.runtime.state_store import get_state_db_path
from app.execution.sql_safety import create_read_only_connection


class StartupCheckError(RuntimeError):
    """시작 점검 실패. 서버가 요청을 받기 전에 중단할 때 쓴다."""


def run_startup_checks() -> dict[str, Any]:
    """필수 로컬 자원을 검증한다. 하나라도 실패하면 예외를 올린다."""

    checks = {
        "database": _check_database(),
        "state_store": _check_state_store(),
        "experiment_store": _check_experiment_store(),
        "environment": _check_environment(),
    }
    failed = {name: value for name, value in checks.items() if value.get("status") != "ok"}
    if failed:
        raise StartupCheckError(f"startup validation failed: {', '.join(failed)}")
    return checks


def health_status() -> dict[str, Any]:
    """/health용으로 민감 정보를 뺀 점검 결과를 모은다. 예외는 error 항목으로 남긴다."""

    checks: dict[str, Any] = {}
    for name, func in {
        "database": _check_database,
        "state_store": _check_state_store,
        "experiment_store": _check_experiment_store,
    }.items():
        try:
            checks[name] = func()
        except Exception as exc:
            checks[name] = {"status": "error", "message": _safe_message(exc)}
    checks["status"] = "ok" if all(value.get("status") == "ok" for value in checks.values() if isinstance(value, dict)) else "error"
    return checks


def _check_database() -> dict[str, Any]:
    """주문 DB가 준비되어 있고 사용자 테이블이 있는지 본다."""

    ensure_database_ready(DEFAULT_DB_PATH)
    with closing(create_read_only_connection(DEFAULT_DB_PATH)) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    table_names = [row[0] for row in rows if not str(row[0]).startswith("sqlite_")]
    if not table_names:
        raise StartupCheckError("configured database has no user tables")
    return {"status": "ok", "tables": len(table_names), "database": DEFAULT_DB_PATH.name}


def _check_state_store() -> dict[str, Any]:
    """런타임 상태 SQLite에 실제로 쓴 뒤 롤백해 쓰기 가능 여부를 확인한다."""

    path = get_state_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(str(path))) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("CREATE TABLE IF NOT EXISTS startup_probe (id INTEGER PRIMARY KEY)")
            conn.execute("INSERT INTO startup_probe DEFAULT VALUES")
        finally:
            conn.rollback()
    return {"status": "ok", "database": Path(path).name}


def _check_experiment_store() -> dict[str, Any]:
    """실험 과제 설정에 task_id·prompt가 있는지 본다."""

    config = load_task_config()
    if not config.get("tasks"):
        raise StartupCheckError("experiment task config has no tasks")
    for task in config["tasks"]:
        required = {"task_id", "prompt"}
        missing = required - set(task)
        if missing:
            raise StartupCheckError(f"experiment task missing fields: {', '.join(sorted(missing))}")
    return {"status": "ok", "tasks": len(config["tasks"])}


def _check_environment() -> dict[str, Any]:
    """LLM 설정이 해석되는지 본다. 실제 연결은 여기서 하지 않는다."""

    try:
        provider, *_ = resolve_agent_llm_settings()
    except (RuntimeError, ValueError) as exc:
        raise StartupCheckError(str(exc)) from exc
    return {"status": "ok", "agent_provider": provider}


def _safe_message(exc: Exception) -> str:
    """헬스 메시지에서 데이터 디렉터리 절대 경로를 가린다."""

    return str(exc).replace(str(DEFAULT_DB_PATH.parent), "<data-dir>")
