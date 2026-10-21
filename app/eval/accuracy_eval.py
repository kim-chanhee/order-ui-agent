"""Execution-accuracy evaluation: replay ground-truth questions through the fast SQL
agent and compare its result set against a hand-written expected SQL query.

Usage:
    order-ui-agent-eval-accuracy [--limit N] [--question-id ID] [--output PATH]
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
import math
import sqlite3
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from app.chat.thread_context import agent_cache_context  # noqa: E402
from app.execution.confirmed_execution import execute_schema_question  # noqa: E402
from app.execution.sql_builder import _run_fallback_sql  # noqa: E402
from app.eval.perturbations import expand_with_perturbations  # noqa: E402


DEFAULT_GROUND_TRUTH_PATH = Path("Data/eval/ground_truth.json")
DEFAULT_RESULTS_DIR = Path("Data/eval/results")


@dataclass
class EvalOutcome:
    id: str
    question: str
    passed: bool
    error: str
    error_category: str
    expected_row_count: int
    agent_row_count: int
    expected_columns: list[str]
    agent_columns: list[str]
    agent_sql: str
    elapsed_ms: int
    base_id: str = ""
    perturbation_kind: str = "original"
    result_fingerprint: str = ""


def _normalize_value(value: Any) -> tuple[str, Any]:
    if value is None:
        return ("null", None)
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return ("number", float(value))
    text = str(value).strip()
    try:
        number = float(text)
    except ValueError:
        return ("text", text.casefold())
    return ("number", number)


def _row_values(row: Any, columns: list[str]) -> list[Any]:
    if isinstance(row, dict):
        return [row.get(column) for column in columns]
    return list(row)


def _values_equal(left: Any, right: Any) -> bool:
    left_kind, left_value = _normalize_value(left)
    right_kind, right_value = _normalize_value(right)
    if left_kind == right_kind == "number":
        return math.isclose(left_value, right_value, rel_tol=1e-6, abs_tol=1e-9)
    return (left_kind, left_value) == (right_kind, right_value)


def _rows_equal(
    expected_rows: list[Any],
    expected_columns: list[str],
    agent_rows: list[Any],
    agent_columns: list[str],
    *,
    order_sensitive: bool,
) -> bool:
    if len(expected_columns) != len(agent_columns) or len(expected_rows) != len(agent_rows):
        return False
    expected = [_row_values(row, expected_columns) for row in expected_rows]
    actual = [_row_values(row, agent_columns) for row in agent_rows]

    def row_equal(left: list[Any], right: list[Any]) -> bool:
        return len(left) == len(right) and all(
            _values_equal(left_value, right_value)
            for left_value, right_value in zip(left, right, strict=True)
        )

    if order_sensitive:
        return all(row_equal(left, right) for left, right in zip(expected, actual, strict=True))

    unmatched = list(actual)
    for expected_row in expected:
        match_index = next(
            (index for index, candidate in enumerate(unmatched) if row_equal(expected_row, candidate)),
            None,
        )
        if match_index is None:
            return False
        unmatched.pop(match_index)
    return not unmatched


def run_expected_sql(expected_sql: str) -> tuple[list[str], list[sqlite3.Row]]:
    return _run_fallback_sql(expected_sql)


def _comparison_error(
    expected_columns: list[str],
    expected_rows: list[Any],
    agent_columns: list[str],
    agent_rows: list[Any],
) -> tuple[str, str]:
    if len(expected_columns) != len(agent_columns):
        return "projection_mismatch", (
            f"expected {len(expected_columns)} output columns but agent returned "
            f"{len(agent_columns)}"
        )
    if len(expected_rows) != len(agent_rows):
        return "row_count_mismatch", (
            f"expected {len(expected_rows)} rows but agent returned {len(agent_rows)}"
        )
    return "result_value_mismatch", "result values or required ordering do not match"


def evaluate_item(item: dict[str, Any]) -> EvalOutcome:
    question = item["question"]
    started = time.perf_counter()
    try:
        expected_columns, expected_rows = run_expected_sql(item["expected_sql"])
    except Exception as exc:  # noqa: BLE001 - ground truth must still be reported
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return EvalOutcome(
            id=item["id"],
            question=question,
            passed=False,
            error=f"ground truth SQL failed: {exc}",
            error_category="ground_truth_error",
            expected_row_count=0,
            agent_row_count=0,
            expected_columns=[],
            agent_columns=[],
            agent_sql="",
            elapsed_ms=elapsed_ms,
            base_id=str(item.get("base_id") or item["id"]),
            perturbation_kind=str(item.get("perturbation_kind") or "original"),
        )

    cached_context = agent_cache_context(None, question) or None
    result = execute_schema_question(question, cached_context=cached_context)
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    if result.fallback_used or result.analysis_payload is None:
        return EvalOutcome(
            id=item["id"],
            question=question,
            passed=False,
            error=result.fallback_error or "agent returned no result",
            error_category="agent_execution_failure",
            expected_row_count=len(expected_rows),
            agent_row_count=0,
            expected_columns=expected_columns,
            agent_columns=[],
            agent_sql="",
            elapsed_ms=elapsed_ms,
            base_id=str(item.get("base_id") or item["id"]),
            perturbation_kind=str(item.get("perturbation_kind") or "original"),
        )

    agent_rows = result.analysis_payload.get("rows", [])
    agent_columns = [str(column) for column in result.analysis_payload.get("columns", [])]
    agent_sql = result.analysis_payload.get("sql", "")
    fingerprint = _result_fingerprint(agent_columns, agent_rows)
    order_sensitive = bool(item.get("order_sensitive"))
    passed = _rows_equal(
        expected_rows,
        expected_columns,
        agent_rows,
        agent_columns,
        order_sensitive=order_sensitive,
    )
    category, detail = ("", "") if passed else _comparison_error(
        expected_columns,
        expected_rows,
        agent_columns,
        agent_rows,
    )
    return EvalOutcome(
        id=item["id"],
        question=question,
        passed=passed,
        error=detail,
        error_category=category,
        expected_row_count=len(expected_rows),
        agent_row_count=len(agent_rows),
        expected_columns=expected_columns,
        agent_columns=agent_columns,
        agent_sql=agent_sql,
        elapsed_ms=elapsed_ms,
        base_id=str(item.get("base_id") or item["id"]),
        perturbation_kind=str(item.get("perturbation_kind") or "original"),
        result_fingerprint=fingerprint,
    )


def _result_fingerprint(columns: list[str], rows: list[Any]) -> str:
    payload = json.dumps(
        {"columns": columns, "rows": rows},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return sha256(payload.encode("utf-8")).hexdigest()[:16]


def stability_summary(outcomes: list[EvalOutcome]) -> dict[str, Any]:
    grouped: dict[str, list[EvalOutcome]] = defaultdict(list)
    for outcome in outcomes:
        grouped[outcome.base_id or outcome.id.split("@run", 1)[0]].append(outcome)
    stable = 0
    for group in grouped.values():
        signatures = {(outcome.passed, outcome.result_fingerprint) for outcome in group}
        stable += int(len(signatures) == 1)
    return {
        "groups": len(grouped),
        "stable_groups": stable,
        "stability": stable / len(grouped) if grouped else 0.0,
    }


def load_ground_truth(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    return data["items"]


def print_summary(outcomes: list[EvalOutcome]) -> None:
    passed = sum(1 for outcome in outcomes if outcome.passed)
    total = len(outcomes)
    for outcome in outcomes:
        mark = "PASS" if outcome.passed else "FAIL"
        detail = f" ({outcome.error})" if outcome.error else ""
        print(f"[{mark}] {outcome.id}{detail}")
    accuracy = (passed / total * 100) if total else 0.0
    print(f"\n{passed}/{total} passed ({accuracy:.1f}%)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ground-truth", type=Path, default=DEFAULT_GROUND_TRUTH_PATH)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--question-id", type=str, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--with-perturbations", action="store_true")
    parser.add_argument("--variants-per-item", type=int, default=6)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--min-accuracy", type=float, default=None)
    args = parser.parse_args()

    items = load_ground_truth(args.ground_truth)
    if args.question_id:
        items = [item for item in items if item["id"] == args.question_id]
        if not items:
            raise SystemExit(f"no ground-truth item with id={args.question_id!r}")
    elif args.limit is not None:
        items = items[: args.limit]

    if args.with_perturbations:
        items = expand_with_perturbations(items, variants_per_item=args.variants_per_item)
    if args.runs < 1:
        raise SystemExit("--runs must be at least 1")

    outcomes: list[EvalOutcome] = []
    for run_number in range(1, args.runs + 1):
        for item in items:
            run_item = dict(item)
            run_item.setdefault("base_id", str(item["id"]))
            if args.runs > 1:
                run_item["id"] = f"{item['id']}@run{run_number}"
            outcomes.append(evaluate_item(run_item))
    print_summary(outcomes)

    output_path = args.output
    if output_path is None:
        DEFAULT_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output_path = DEFAULT_RESULTS_DIR / f"run_{timestamp}.json"
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)

    passed = sum(1 for outcome in outcomes if outcome.passed)
    total = len(outcomes)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ground_truth_path": str(args.ground_truth),
        "total": total,
        "passed": passed,
        "accuracy": (passed / total) if total else 0.0,
        "runs": args.runs,
        "perturbations_enabled": args.with_perturbations,
        "failure_categories": dict(Counter(
            outcome.error_category for outcome in outcomes if outcome.error_category
        )),
        "stability": stability_summary(outcomes),
        "outcomes": [asdict(outcome) for outcome in outcomes],
    }
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
    print(f"\nreport written to {output_path}")
    if args.min_accuracy is not None and total and passed / total < args.min_accuracy:
        raise SystemExit(
            f"accuracy gate failed: {passed / total:.3f} < {args.min_accuracy:.3f}"
        )


if __name__ == "__main__":
    main()
