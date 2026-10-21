"""Experiment task criteria and semantic scoring helpers."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


TASK_CONFIG_PATH = Path(__file__).with_name("tasks.json")


@lru_cache(maxsize=1)
def load_task_config() -> dict[str, Any]:
    """Load researcher-editable task criteria."""

    with TASK_CONFIG_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def get_task(task_id: str | None) -> dict[str, Any] | None:
    for task in load_task_config().get("tasks", []):
        if task.get("task_id") == task_id:
            return dict(task)
    return None


def task_ids() -> list[str]:
    return [task["task_id"] for task in load_task_config().get("tasks", [])]


def task_complexity(task_id: str | None) -> str:
    return str((get_task(task_id) or {}).get("complexity") or "")


def score_plan_semantics(plan: dict[str, Any] | None, task_id: str | None) -> bool | None:
    """Return whether a review uses the generic schema-driven contract."""

    task = get_task(task_id)
    if not task or not isinstance(plan, dict):
        return None
    return (
        plan.get("intent") == "schema_driven_query"
        and bool(str(plan.get("original_question") or "").strip())
    )


def score_result_accuracy(result_payload: dict[str, Any] | None, task_id: str | None) -> bool | None:
    """Return a coarse automated result check from researcher criteria."""

    task = get_task(task_id)
    if not task or not isinstance(result_payload, dict):
        return None
    expected = task.get("expected_result") or {}
    min_rows = expected.get("min_row_count")
    if min_rows is None:
        return None
    rows = result_payload.get("rows") or []
    return isinstance(rows, list) and len(rows) >= int(min_rows)
