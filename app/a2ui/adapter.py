"""두 모드의 조회 결과를 공통 A2UI 화면 형식으로 변환한다.

A2UI 모드 전용 계획 검토 화면 생성은 review.py에서 담당한다.
"""

from __future__ import annotations

from uuid import uuid4

from app.a2ui.catalog import COMPONENT_FALLBACKS, DEFAULT_SUPPORTED_COMPONENTS
from app.a2ui.models import A2UIAction, A2UIClientCapabilities, A2UIComponent, A2UISurface


def analysis_result_to_surface(
    result: dict,
    *,
    answer: str = "",
    input_source: str = "",
    provider: str = "",
    fallback_used: bool = False,
    fallback_error: str = "",
    capabilities: A2UIClientCapabilities | None = None,
) -> A2UISurface:
    supported = _supported_set(capabilities)
    metadata = dict(result.get("metadata") or {})
    if provider:
        metadata["provider"] = provider
    metadata["fallback_used"] = bool(fallback_used)
    if fallback_error:
        metadata["fallback_error"] = fallback_error
    rows = result.get("rows") or []
    columns = result.get("columns") or []
    fallbacks: list[dict[str, str]] = []
    data_model = {
        "answer": answer,
        "input_source": input_source,
        "sql": result.get("sql") or "",
        "params": result.get("params") or [],
        "columns": columns,
        "rows": rows,
        "metadata": metadata,
        "date_from": result.get("date_from"),
        "date_to": result.get("date_to"),
        "anchor_event": result.get("anchor_event"),
        "anchor_time": result.get("anchor_time"),
    }
    requested_view = metadata.get("result_view") or "table"
    requested_types: list[str]
    if not rows or requested_view == "summary":
        requested_types = ["text"]
    elif requested_view == "chart":
        requested_types = ["bar_chart"]
    elif requested_view == "table_and_chart":
        requested_types = ["bar_chart", "table"]
    else:
        requested_types = ["table"]
    components = []
    for index, requested_type in enumerate(requested_types):
        component_type = _supported_type(requested_type, supported, fallbacks)
        component_data = {}
        if requested_type == "text":
            component_data = {"label": "실행 결과", "description": answer or "조회 결과가 없습니다."}
        components.append(
            A2UIComponent(
                component_id=f"result_{index + 1}_{component_type}",
                component_type=component_type,
                data_model=component_data,
            )
        )
    return A2UISurface(
        surface_id=str(uuid4()),
        revision=1,
        surface_type="result",
        data_model=data_model,
        components=components,
        actions=[A2UIAction(action_id="start_new_query", action_type="start_new_query", label="새 질문")],
        compatibility={"fallbacks": fallbacks, "supported_components": sorted(supported)},
    )


def _supported_set(capabilities: A2UIClientCapabilities | None) -> set[str]:
    if not capabilities or not capabilities.supported_components:
        return set(DEFAULT_SUPPORTED_COMPONENTS)
    declared = set(capabilities.supported_components) & set(DEFAULT_SUPPORTED_COMPONENTS)
    return declared or {"text"}


def _supported_type(component_type: str, supported: set[str], fallbacks: list[dict[str, str]]) -> str:
    if component_type in supported:
        return component_type
    fallback = COMPONENT_FALLBACKS.get(component_type, "review")
    if fallback not in supported:
        fallback = next(
            (candidate for candidate in ("text", "review", "notice", "table") if candidate in supported),
            sorted(supported)[0],
        )
    fallbacks.append({"from": component_type, "to": fallback})
    return fallback
