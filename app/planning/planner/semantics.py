"""분석 지표·관계 범위를 정리하고 분석 의미와 날짜 안내의 일관성을 검증한다."""

from __future__ import annotations

import re

from app.execution.analysis_semantics import load_analysis_semantics
from app.planning.ui_models import DynamicPlannerOutput


def _normalize_identifier_count(
    output: DynamicPlannerOutput,
) -> DynamicPlannerOutput:
    """건수 지표의 고유 대상 집계를 보장하고 관계 확장 중복을 방지한다는 안내를 반영한다."""

    metric = output.analysis_plan.metric
    if not metric or metric.kind != "count":
        return output
    output.analysis_plan.metric = metric.model_copy(update={"distinct": True})
    output.warnings = [warning for warning in output.warnings if "행" not in warning]
    normalized_metric = output.analysis_plan.metric
    label = normalized_metric.unit or normalized_metric.field or "식별자"
    warning = f"관계 확장 중복을 피하기 위해 고유 {label} 수로 집계합니다."
    if warning not in output.warnings:
        output.warnings.append(warning)
    return output


def _normalize_detail_result_metric(
    output: DynamicPlannerOutput,
) -> DynamicPlannerOutput:
    """표시 이름을 포함한 상세 목록 요청에 그룹 기준 없이 붙은 단일 건수 지표와 관련 정렬을 제거한다."""

    plan = output.analysis_plan
    metric = plan.metric
    requested = {str(value).strip().casefold() for value in plan.requested_attributes}
    if (
        metric is None
        or metric.kind != "count"
        or "display_name" not in requested
        or not plan.result_grain
        or plan.group_by
    ):
        return output
    plan.metric = None
    plan.sort = [item for item in plan.sort if item.field.casefold() != "metric"]
    warning = "속성 목록 요청으로 해석하여 단일 건수 집계 대신 결과 단위별 상세를 반환합니다."
    if warning not in output.warnings:
        output.warnings.append(warning)
    return output


def _normalize_relationship_scope(
    output: DynamicPlannerOutput,
) -> DynamicPlannerOutput:
    """표시 이름을 얻는 관계가 의미 메타데이터에서 하나로 정해지면 계획의 관계 범위를 보정한다."""

    plan = output.analysis_plan
    requested = {str(value).strip().casefold() for value in plan.requested_attributes}
    if "display_name" not in requested or not plan.target_entity:
        return output
    semantics = load_analysis_semantics()
    target = plan.target_entity.strip().casefold()
    display_via: str | None = None
    for entity_name, definition in (semantics.get("entity_roles") or {}).items():
        if not isinstance(definition, dict):
            continue
        terms = {
            str(entity_name).strip().casefold(),
            *(str(value).strip().casefold() for value in definition.get("semantic_terms", [])),
        }
        if target in terms:
            display_via = str(definition.get("display_name_via") or "").strip().casefold() or None
            break
    if not display_via:
        return output
    candidates = [
        str(edge.get("name") or "").strip()
        for edge in semantics.get("entity_relationships", [])
        if isinstance(edge, dict)
        and str(edge.get("source_entity") or "").strip().casefold() == target
        and str(edge.get("target_entity") or "").strip().casefold() == display_via
        and str(edge.get("name") or "").strip()
    ]
    if len(candidates) != 1:
        return output
    previous_scope = plan.relationship_scope
    plan.relationship_scope = candidates[0]
    warning = f"표시 이름은 스키마에 정의된 관계 범위({candidates[0]})로 연결합니다."
    if previous_scope and previous_scope != candidates[0]:
        warning = (
            f"표시 이름 관계를 {previous_scope} 대신 스키마에 정의된 "
            f"{candidates[0]}로 교정했습니다."
        )
    if warning not in output.warnings:
        output.warnings.append(warning)
    return output


def _promote_headline_metric(output: DynamicPlannerOutput) -> DynamicPlannerOutput:
    """대표 지표가 비어 있고 지표 목록이 있으면 첫 지표를 복사해 대표 지표로 설정한다."""

    plan = output.analysis_plan
    if plan.metric is None and plan.metrics:
        plan.metric = plan.metrics[0].model_copy(deep=True)
    return output


def _mirror_infeasible_into_unresolved(output: DynamicPlannerOutput) -> DynamicPlannerOutput:
    """조회 불가 사유를 미해결 조건에도 복사해 실행 전 확인 단계에서 차단되도록 한다."""

    if not output.infeasible:
        return output
    plan = output.analysis_plan
    existing = list(plan.unresolved_constraints)
    seen = {item.strip() for item in existing}
    for condition in output.infeasible:
        reason = condition.reason.strip()
        if reason and reason not in seen:
            existing.append(reason)
            seen.add(reason)
    plan.unresolved_constraints = existing
    return output


def _validate_planner_semantics(output: DynamicPlannerOutput, question: str) -> None:
    """비율 요청과 지표의 일치, 분자·분모, 요청 속성의 대상·결과 단위·관계 범위를 검증한다."""

    metrics = ([output.analysis_plan.metric] if output.analysis_plan.metric else []) + output.analysis_plan.metrics
    ratio_requested = bool(
        re.search(r"(?:비율|백분율|퍼센트|[가-힣A-Za-z]+[율률])(?:이|가|을|를|은|는|로|과|와|의|\s|$)", question)
        or re.search(r"\b(?:ratio|rate|percentage|percent)\b", question, re.IGNORECASE)
        or "%" in question
    )
    if ratio_requested and not any(metric.kind == "ratio" for metric in metrics):
        raise ValueError("the question requests a ratio/rate, so metric.kind must be ratio")
    if any(metric.kind == "ratio" and (not metric.numerator or not metric.denominator) for metric in metrics):
        raise ValueError("ratio metric requires both numerator and denominator semantics")
    requested_attributes = {
        str(value).strip().casefold() for value in output.analysis_plan.requested_attributes if str(value).strip()
    }
    if requested_attributes and not output.analysis_plan.target_entity:
        raise ValueError("requested attributes require target_entity")
    if "display_name" in requested_attributes and not output.analysis_plan.result_grain:
        raise ValueError("display_name requests require an explicit result_grain")
    if "display_name" in requested_attributes and output.analysis_plan.target_entity:
        semantics = load_analysis_semantics()
        target = output.analysis_plan.target_entity.strip().casefold()
        for entity_name, definition in (semantics.get("entity_roles") or {}).items():
            if not isinstance(definition, dict):
                continue
            terms = {
                str(entity_name).strip().casefold(),
                *(str(value).strip().casefold() for value in definition.get("semantic_terms", [])),
            }
            if target not in terms:
                continue
            if definition.get("display_name_via") and not output.analysis_plan.relationship_scope:
                raise ValueError(
                    "display_name for the selected entity requires an explicit relationship_scope"
                )
            break


def _synchronize_temporal_copy(output: DynamicPlannerOutput) -> DynamicPlannerOutput:
    """확정된 기간과 다른 날짜가 요약이나 경고에 나타나면 해당 문구를 교정하거나 제거한다."""

    anchor = output.analysis_plan.date_anchor
    if not anchor or not anchor.resolved_date_from or not anchor.resolved_date_to:
        return output
    allowed = {str(anchor.resolved_date_from), str(anchor.resolved_date_to)}
    mentioned = set(re.findall(r"\b\d{4}-\d{2}-\d{2}\b", output.summary))
    if mentioned - allowed:
        output.summary = (
            f"데이터 기준 기간은 {anchor.resolved_date_from}~{anchor.resolved_date_to}입니다. "
            "아래에 확정된 지표와 집계 기준으로 분석합니다."
        )
    output.warnings = [
        warning for warning in output.warnings
        if not (set(re.findall(r"\b\d{4}-\d{2}-\d{2}\b", warning)) - allowed)
    ]
    return output
