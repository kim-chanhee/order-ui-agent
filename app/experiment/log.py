"""CSV experiment interaction logging.

실험 참가자의 질문, 생성된 UI plan, 실행 결과, 소요 시간을 CSV로 남긴다.
웹 기능 자체와 분리한 이유는 라우트/채팅 로직이 CSV 컬럼 세부사항을
몰라도 되게 하기 위해서다.
"""

from __future__ import annotations

import csv
import json
import threading
from datetime import datetime, timezone
from typing import Any

from app.data.database import DEFAULT_DB_PATH


# Data/experiment_interactions.csv에 누적 기록한다.
# 여러 요청이 동시에 끝날 수 있으므로 파일 쓰기는 lock으로 직렬화한다.
EXPERIMENT_CSV_PATH = DEFAULT_DB_PATH.parent / "experiment_interactions.csv"
EXPERIMENT_CSV_LOCK = threading.Lock()

EXPERIMENT_CSV_FIELDS = [
    "created_at",
    "participant_id",
    "thread_id",
    "run_id",
    "stage",
    "input_source",
    "gender",
    "age",
    "education",
    "occupation",
    "ai_experience",
    "llm_frequency",
    "ai_tools",
    "ai_tools_other",
    "question",
    "assistant_answer",
    "missing_fields",
    "warnings",
    "ui_blocks_json",
    "ui_state_json",
    "analysis_plan_version",
    "analysis_plan_json",
    "planner_source",
    "planner_confidence",
    "group_by_json",
    "date_anchor_json",
    "unresolved_constraints_json",
    "additional_constraint",
    "additional_constraints",
    "suggested_constraints_json",
    "selected_suggestion_id",
    "surface_id",
    "revision",
    "refinement_count",
    "field_metadata_json",
    "changed_fields_json",
    "plan_diff_json",
    "plan_changed",
    "changed_field_count",
    "time_to_plan_ms",
    "time_to_confirm_ms",
    "time_to_answer_ms",
    "plan_json",
    "execution_result_json",
]


def append_experiment_csv(
    *,
    participant_id: str | None,
    participant_profile: dict[str, Any] | None,
    thread_id: str | None,
    run_id: str | None,
    stage: str,
    input_source: str | None,
    question: str,
    assistant_answer: str | None,
    plan: dict | None = None,
    execution_result: dict | None = None,
    time_to_plan_ms: int | None = None,
    time_to_confirm_ms: int | None = None,
    time_to_answer_ms: int | None = None,
    changed_fields: list[str] | None = None,
    plan_diff: list[dict[str, Any]] | None = None,
    plan_changed: bool | None = None,
    additional_constraint: str | None = None,
    selected_suggestion_id: str | None = None,
    surface_id: str | None = None,
    revision: int | None = None,
    refinement_count: int | None = None,
) -> None:
    """Append one experiment interaction row."""

    # 관리자 모드처럼 참가자 정보가 없는 요청은 실험 데이터로 기록하지 않는다.
    if not participant_id or not participant_profile:
        return
    profile = participant_profile or {}
    plan = plan or None
    # plan 내부의 UI 상태/블록을 컬럼별로도 꺼내고, 전체 JSON도 함께 저장한다.
    # 나중에 실험 분석에서 필드별 통계와 원본 재현을 둘 다 할 수 있게 하기 위함이다.
    ui_state = (plan or {}).get("ui_state") if isinstance(plan, dict) else None
    ui_blocks = (plan or {}).get("ui_blocks") if isinstance(plan, dict) else None
    missing_fields = (plan or {}).get("missing_fields") if isinstance(plan, dict) else None
    warnings = (plan or {}).get("warnings") if isinstance(plan, dict) else None
    analysis_plan = (plan or {}).get("analysis_plan") if isinstance(plan, dict) else None
    current_constraint = additional_constraint or ""
    if not current_constraint and isinstance(ui_state, dict):
        current_constraint = str(ui_state.get("additional_constraint") or "")
    structured_constraints = ""
    if isinstance(analysis_plan, dict):
        structured_constraints = json.dumps(analysis_plan.get("filters") or [], ensure_ascii=False)
    row = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "participant_id": participant_id or "",
        "thread_id": thread_id or "",
        "run_id": run_id or "",
        "stage": stage,
        "input_source": input_source or "",
        "gender": profile.get("gender", ""),
        "age": profile.get("age", ""),
        "education": profile.get("education", ""),
        "occupation": profile.get("occupation", ""),
        "ai_experience": profile.get("ai_experience", ""),
        "llm_frequency": profile.get("llm_frequency", ""),
        "ai_tools": "|".join(profile.get("ai_tools") or []),
        "ai_tools_other": profile.get("ai_tools_other", ""),
        "question": question,
        "assistant_answer": assistant_answer or "",
        "missing_fields": "|".join(missing_fields or []) if isinstance(missing_fields, list) else "",
        "warnings": " | ".join(warnings or []) if isinstance(warnings, list) else "",
        "ui_blocks_json": json.dumps(ui_blocks, ensure_ascii=False) if ui_blocks is not None else "",
        "ui_state_json": json.dumps(ui_state, ensure_ascii=False) if ui_state is not None else "",
        "analysis_plan_version": _analysis_plan_value(analysis_plan, "version"),
        "analysis_plan_json": json.dumps(analysis_plan, ensure_ascii=False) if analysis_plan is not None else "",
        "planner_source": _analysis_plan_value(analysis_plan, "source"),
        "planner_confidence": _analysis_plan_value(analysis_plan, "confidence"),
        "group_by_json": json.dumps((analysis_plan or {}).get("group_by"), ensure_ascii=False) if isinstance(analysis_plan, dict) else "",
        "date_anchor_json": json.dumps((analysis_plan or {}).get("date_anchor"), ensure_ascii=False) if isinstance(analysis_plan, dict) else "",
        "unresolved_constraints_json": json.dumps((analysis_plan or {}).get("unresolved_constraints"), ensure_ascii=False) if isinstance(analysis_plan, dict) else "",
        "additional_constraint": current_constraint,
        "additional_constraints": structured_constraints,
        "suggested_constraints_json": json.dumps((plan or {}).get("suggested_constraints"), ensure_ascii=False) if isinstance(plan, dict) else "",
        "selected_suggestion_id": selected_suggestion_id or ((plan or {}).get("selected_suggestion_id", "") if isinstance(plan, dict) else ""),
        "surface_id": surface_id or ((plan or {}).get("surface_id", "") if isinstance(plan, dict) else ""),
        "revision": revision if revision is not None else ((plan or {}).get("revision", "") if isinstance(plan, dict) else ""),
        "refinement_count": refinement_count if refinement_count is not None else ((plan or {}).get("refinement_count", 0) if isinstance(plan, dict) else 0),
        "field_metadata_json": json.dumps((analysis_plan or {}).get("field_metadata"), ensure_ascii=False) if isinstance(analysis_plan, dict) else "",
        "changed_fields_json": _format_changed_fields(changed_fields),
        "plan_diff_json": json.dumps(plan_diff, ensure_ascii=False) if plan_diff else "",
        "plan_changed": "" if plan_changed is None else str(bool(plan_changed)).lower(),
        "changed_field_count": str(len(_unique_changed_fields(changed_fields))),
        "time_to_plan_ms": _format_timing_ms(time_to_plan_ms),
        "time_to_confirm_ms": _format_timing_ms(time_to_confirm_ms),
        "time_to_answer_ms": _format_timing_ms(time_to_answer_ms),
        "plan_json": json.dumps(plan, ensure_ascii=False) if plan is not None else "",
        "execution_result_json": json.dumps(execution_result, ensure_ascii=False) if execution_result is not None else "",
    }
    EXPERIMENT_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with EXPERIMENT_CSV_LOCK:
        # 오래된 CSV가 남아 있어도 현재 컬럼 정의에 맞춰 자동 보정한 뒤 append한다.
        _ensure_experiment_csv_header()
        write_header = not EXPERIMENT_CSV_PATH.exists()
        with EXPERIMENT_CSV_PATH.open("a", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=EXPERIMENT_CSV_FIELDS)
            if write_header:
                writer.writeheader()
            writer.writerow(row)


def _ensure_experiment_csv_header() -> None:
    """Rewrite an existing CSV if its header differs from the current schema."""

    if not EXPERIMENT_CSV_PATH.exists():
        return
    with EXPERIMENT_CSV_PATH.open("r", newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        existing_fields = reader.fieldnames or []
        if existing_fields == EXPERIMENT_CSV_FIELDS:
            return
        rows = list(reader)
    with EXPERIMENT_CSV_PATH.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=EXPERIMENT_CSV_FIELDS)
        writer.writeheader()
        for existing_row in rows:
            writer.writerow({field: existing_row.get(field, "") for field in EXPERIMENT_CSV_FIELDS})


def _format_timing_ms(value: int | None) -> str:
    if value is None:
        return ""
    return str(max(0, int(value)))


def _format_changed_fields(value: list[str] | None) -> str:
    """Deduplicate changed UI field names and serialize them as JSON."""

    fields = _unique_changed_fields(value)
    return json.dumps(fields, ensure_ascii=False) if fields else ""


def _unique_changed_fields(value: list[str] | None) -> list[str]:
    if not value:
        return []
    fields: list[str] = []
    for field in value:
        if isinstance(field, str) and field and field not in fields:
            fields.append(field)
    return fields


def _analysis_plan_value(analysis_plan: Any, key: str) -> str:
    if not isinstance(analysis_plan, dict):
        return ""
    value = analysis_plan.get(key)
    return "" if value is None else str(value)
