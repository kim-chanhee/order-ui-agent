"""A2UI 전용 검토 화면과 최신 계획 버전을 SQLite에 저장·조회한다.

DB 연결과 plan_surfaces 테이블 생성은 공통 state_store를 사용한다.
"""

from __future__ import annotations

from contextlib import closing

from app.runtime.state_store import _connect, _json_dumps, _json_loads, _now_iso


def save_plan_surface(
    *,
    surface_id: str,
    plan_id: str,
    revision: int,
    plan: dict,
    surface: dict,
    participant_id: str | None = None,
    thread_id: str | None = None,
) -> None:
    """Persist the latest server-issued plan surface revision."""

    now = _now_iso()
    with closing(_connect()) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO plan_surfaces (
                    surface_id, plan_id, revision, participant_id, thread_id,
                    plan_json, surface_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(surface_id) DO UPDATE SET
                    plan_id = excluded.plan_id,
                    revision = excluded.revision,
                    participant_id = excluded.participant_id,
                    thread_id = excluded.thread_id,
                    plan_json = excluded.plan_json,
                    surface_json = excluded.surface_json,
                    updated_at = excluded.updated_at
                """,
                (
                    surface_id,
                    plan_id,
                    int(revision),
                    participant_id,
                    thread_id,
                    _json_dumps(plan),
                    _json_dumps(surface),
                    now,
                    now,
                ),
            )


def get_plan_surface(surface_id: str | None) -> dict | None:
    """Return a persisted plan surface revision."""

    if not surface_id:
        return None
    with closing(_connect()) as conn:
        row = conn.execute(
            """
            SELECT surface_id, plan_id, revision, participant_id, thread_id, plan_json, surface_json
            FROM plan_surfaces
            WHERE surface_id = ?
            """,
            (surface_id,),
        ).fetchone()
    if not row:
        return None
    return {
        "surface_id": row["surface_id"],
        "plan_id": row["plan_id"],
        "revision": row["revision"],
        "participant_id": row["participant_id"],
        "thread_id": row["thread_id"],
        "plan": _json_loads(row["plan_json"], {}),
        "surface": _json_loads(row["surface_json"], {}),
    }
