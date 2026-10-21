from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from app.data.database import DEFAULT_DB_PATH
from app.experiment.log import EXPERIMENT_CSV_FIELDS


LEGACY_EXPERIMENT_CSV_FIELDS = [
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
    "plan_json",
    "execution_result_json",
]


def load_experiment_rows(path: str | Path) -> list[dict[str, str]]:
    csv_path = Path(path)
    if not csv_path.exists():
        return []

    with csv_path.open("r", newline="", encoding="utf-8-sig") as file:
        sample = file.readline()
        file.seek(0)
        first_cell = sample.split(",", 1)[0].strip()
        if first_cell == "created_at":
            rows = list(csv.DictReader(file))
        else:
            rows = list(csv.DictReader(file, fieldnames=LEGACY_EXPERIMENT_CSV_FIELDS))

    return [_normalize_row(row) for row in rows]


def summarize_experiment_rows(rows: list[dict[str, str]]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "total_rows": len(rows),
        "by_input_source": {},
    }
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[row.get("input_source") or "unknown"].append(row)

    for input_source, source_rows in sorted(grouped.items()):
        stage_counts = Counter(row.get("stage") or "unknown" for row in source_rows)
        changed_field_counts: Counter[str] = Counter()
        missing_field_counts: Counter[str] = Counter()
        changed_field_sizes: list[int] = []

        for row in source_rows:
            changed_fields = _parse_json_list(row.get("changed_fields_json"))
            changed_field_sizes.append(len(changed_fields))
            changed_field_counts.update(changed_fields)
            missing_field_counts.update(_parse_pipe_list(row.get("missing_fields")))

        summary["by_input_source"][input_source] = {
            "rows": len(source_rows),
            "stage_counts": dict(sorted(stage_counts.items())),
            "avg_time_to_plan_ms": _avg_int_field(source_rows, "time_to_plan_ms"),
            "avg_time_to_confirm_ms": _avg_int_field(source_rows, "time_to_confirm_ms"),
            "avg_time_to_answer_ms": _avg_int_field(source_rows, "time_to_answer_ms"),
            "avg_changed_fields": round(mean(changed_field_sizes), 2) if changed_field_sizes else None,
            "changed_field_counts": dict(sorted(changed_field_counts.items())),
            "missing_field_counts": dict(sorted(missing_field_counts.items())),
        }

    return summary


def render_summary_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Experiment Interaction Summary",
        "",
        f"- total_rows: {summary.get('total_rows', 0)}",
        "",
    ]
    by_source = summary.get("by_input_source") or {}
    if not by_source:
        lines.append("No experiment rows found.")
        return "\n".join(lines)

    for input_source, data in by_source.items():
        lines.extend(
            [
                f"## {input_source}",
                "",
                f"- rows: {data.get('rows', 0)}",
                f"- stage_counts: {_format_mapping(data.get('stage_counts'))}",
                f"- avg_time_to_plan_ms: {_format_optional(data.get('avg_time_to_plan_ms'))}",
                f"- avg_time_to_confirm_ms: {_format_optional(data.get('avg_time_to_confirm_ms'))}",
                f"- avg_time_to_answer_ms: {_format_optional(data.get('avg_time_to_answer_ms'))}",
                f"- avg_changed_fields: {_format_optional(data.get('avg_changed_fields'))}",
                f"- changed_field_counts: {_format_mapping(data.get('changed_field_counts'))}",
                f"- missing_field_counts: {_format_mapping(data.get('missing_field_counts'))}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize order-ui-agent experiment CSV logs.")
    parser.add_argument(
        "csv_path",
        nargs="?",
        default=str(DEFAULT_DB_PATH.parent / "experiment_interactions.csv"),
        help="Path to experiment_interactions.csv",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON instead of Markdown")
    args = parser.parse_args()

    summary = summarize_experiment_rows(load_experiment_rows(args.csv_path))
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(render_summary_markdown(summary))


def _normalize_row(row: dict[str, str | None]) -> dict[str, str]:
    normalized = {field: row.get(field) or "" for field in EXPERIMENT_CSV_FIELDS}
    for key, value in row.items():
        if key is not None and key not in normalized:
            normalized[key] = value or ""
    return normalized


def _avg_int_field(rows: list[dict[str, str]], field: str) -> int | None:
    values: list[int] = []
    for row in rows:
        value = row.get(field)
        if not value:
            continue
        try:
            values.append(int(value))
        except ValueError:
            continue
    return round(mean(values)) if values else None


def _parse_json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, str) and item]


def _parse_pipe_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [item for item in value.split("|") if item]


def _format_mapping(value: Any) -> str:
    if not value:
        return "{}"
    return ", ".join(f"{key}={count}" for key, count in value.items())


def _format_optional(value: Any) -> str:
    return "n/a" if value is None else str(value)


if __name__ == "__main__":
    main()
