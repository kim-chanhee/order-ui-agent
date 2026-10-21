"""검토용 UI의 선택지·기본 입력·중복·배치와 스키마 근거를 정리한다."""

from __future__ import annotations

import re
from typing import Any

from app.planning.analysis_models import AnalysisPlan
from app.planning.option_catalog import OUTPUT_VIEW_OPTIONS, build_plan_option_catalog, merge_options
from app.planning.schema_context import PlannerSchemaContext
from app.planning.ui_models import DynamicPlannerOutput, InfeasibleCondition, UiBlock, UiCondition, UiOption
from app.planning.validator import compute_missing_fields


_METRIC_KIND_OPTIONS = [
    UiOption(value="rows", label="상세 목록"),
    UiOption(value="count", label="건수"),
    UiOption(value="ratio", label="비율"),
    UiOption(value="sum", label="합계"),
    UiOption(value="avg", label="평균"),
    UiOption(value="min", label="최솟값"),
    UiOption(value="max", label="최댓값"),
]


_CHOICE_BLOCK_TYPES = {"select", "option_cards", "multi_select", "choice"}


_FIELD_PATH_PREFIX = "analysis_plan."


def _normalize_ui_blocks(blocks: list[UiBlock]) -> list[UiBlock]:
    """UI 경로 접두사를 정리하고 props에 들어간 선택지를 복구한 뒤 빈 선택형 블록을 보정한다."""

    normalized: list[UiBlock] = []
    for block in blocks:
        updates: dict[str, Any] = {}
        if block.field_path and block.field_path.startswith(_FIELD_PATH_PREFIX):
            updates["field_path"] = block.field_path[len(_FIELD_PATH_PREFIX):]
        target_path = updates.get("field_path", block.field_path) or block.key
        if block.type in _CHOICE_BLOCK_TYPES:
            if target_path == "metric.kind":
                # metric.kind는 코드에 정의된 고정 선택지만 허용한다.
                # LLM이 제안한 임의의 값보다 이 목록을 우선해 확인 요청에
                # distinct_orders처럼 유효하지 않은 지표 종류가 전달되지 않게 한다.
                updates["options"] = _METRIC_KIND_OPTIONS
            elif not block.options:
                recovered = _options_from_props(block.props)
                if recovered:
                    updates["options"] = recovered
        if updates:
            block = block.model_copy(update=updates)
        normalized.append(block)
    return _sanitize_choice_blocks(normalized)


def _options_from_props(props: dict[str, Any]) -> list[UiOption]:
    """props의 options 목록에서 유효한 값·이름·설명을 읽어 UiOption 목록으로 복구한다."""

    raw = props.get("options") if isinstance(props, dict) else None
    if not isinstance(raw, list):
        return []
    options: list[UiOption] = []
    for item in raw:
        if not isinstance(item, dict) or "value" not in item:
            continue
        try:
            options.append(
                UiOption(
                    value=str(item["value"]),
                    label=str(item.get("label") or item["value"]),
                    description=item.get("description"),
                )
            )
        except Exception:
            continue
    return options


def _sanitize_choice_blocks(blocks: list[UiBlock]) -> list[UiBlock]:
    """빈 지표 선택지에 기본값을 채우고 나머지 빈 선택형 블록은 텍스트 입력으로 전환한다."""

    sanitized: list[UiBlock] = []
    for block in blocks:
        if block.type in _CHOICE_BLOCK_TYPES and not block.options:
            if (block.field_path or block.key) == "metric.kind":
                block = block.model_copy(update={"options": _METRIC_KIND_OPTIONS})
            else:
                fallback = "textarea" if block.type == "multi_select" else "text"
                block = block.model_copy(update={"type": fallback})
        sanitized.append(block)
    return sanitized


def _ensure_plan_controls(
    output: DynamicPlannerOutput,
    schema_context: PlannerSchemaContext,
) -> DynamicPlannerOutput:
    """스키마 선택지와 기본 편집 블록을 보충하고 UI 개수·주요 항목·필수 입력을 정리한다."""

    if not output.requires_confirmation:
        return output
    plan = output.analysis_plan
    catalog = build_plan_option_catalog(schema_context.text, plan)
    blocks = [_hydrate_block_options(block, catalog) for block in output.ui_blocks]
    paths = {block.field_path or block.key for block in blocks}

    if "date_range" not in paths:
        blocks.append(UiBlock(
            type="date_range", key="date_range", field_path="date_range",
            label="조회 기간", required=False,
            description="기간과 기준 시점을 확인합니다.",
            section="primary",
        ))
    if catalog.event_types and "event_types" not in paths:
        blocks.append(UiBlock(
            type="multi_select", key="event_types", field_path="event_types",
            label="대상 이벤트", required=bool(plan.event_types),
            description="스키마에서 확인된 업무 이벤트 중 분석 대상을 선택합니다.",
            options=catalog.event_types,
            section="advanced",
        ))
    if "metric.kind" not in paths:
        blocks.append(UiBlock(
            type="option_cards", key="metric_kind", field_path="metric.kind",
            label="결과 방식", required=plan.metric is not None,
            description="상세 목록, 건수, 비율 또는 수치 집계 방식을 선택합니다.",
            options=_METRIC_KIND_OPTIONS,
            section="primary",
        ))
    if catalog.group_by and "group_by" not in paths:
        blocks.append(UiBlock(
            type="multi_select", key="group_by", field_path="group_by",
            label="집계 기준", required=False,
            description="고객·주문·상품·일자 등 결과를 나눠 볼 기준입니다.",
            options=catalog.group_by,
            section="primary",
        ))
    if catalog.count_fields and "metric.field" not in paths:
        blocks.append(UiBlock(
            type="option_cards", key="metric_field", field_path="metric.field",
            label="건수 단위", required=False,
            description="중복을 제거해 셀 업무 대상의 기준을 선택합니다.",
            options=catalog.count_fields,
            visible_if=UiCondition(path="metric.kind", operator="eq", value="count"),
            section="advanced",
        ))
    if catalog.count_fields and "metric.numerator" not in paths:
        blocks.append(UiBlock(
            type="select", key="metric_numerator", field_path="metric.numerator",
            label="비율 분자", required=False,
            description="비율의 분자로 셀 대상을 선택합니다 (예: 배송 실패 건수).",
            options=catalog.count_fields,
            visible_if=UiCondition(path="metric.kind", operator="eq", value="ratio"),
            required_if=UiCondition(path="metric.kind", operator="eq", value="ratio"),
            section="advanced",
        ))
    if catalog.count_fields and "metric.denominator" not in paths:
        blocks.append(UiBlock(
            type="select", key="metric_denominator", field_path="metric.denominator",
            label="비율 분모", required=False,
            description="비율의 분모로 셀 대상을 선택합니다 (예: 전체 주문 건수).",
            options=catalog.count_fields,
            visible_if=UiCondition(path="metric.kind", operator="eq", value="ratio"),
            required_if=UiCondition(path="metric.kind", operator="eq", value="ratio"),
            section="advanced",
        ))
    if "comparison" not in paths:
        blocks.append(UiBlock(
            type="choice", key="comparison", field_path="comparison",
            label="비교 기준", required=False,
            options=catalog.comparisons,
            section="advanced",
        ))
    if "output.view" not in paths:
        blocks.append(UiBlock(
            type="choice", key="output_view", field_path="output.view",
            label="결과 표시", required=False,
            options=OUTPUT_VIEW_OPTIONS,
            section="advanced",
        ))

    blocks = _bounded_unique_controls(blocks, limit=12)
    output.ui_blocks = _cap_primary_controls(blocks, plan)
    output = _flag_ungrounded_group_by(output, schema_context.text)
    output.missing_fields = compute_missing_fields(plan, output.ui_blocks)
    return output


_UNGROUNDED_DIMENSION_HINT = re.compile(
    r"나이|연령|세대|성별|남녀|지역|지방|국가|도시|권역|등급|소득|연봉|채널|유입|경로|"
    r"요일|시간대|계절|분기|매체|플랫폼|디바이스|기기|앱|웹|브라우저|"
    r"age|gender|region|city|country|tier|income|channel|weekday|quarter|season|device|platform",
    re.IGNORECASE,
)


def _flag_ungrounded_group_by(output: DynamicPlannerOutput, schema_text: str) -> DynamicPlannerOutput:
    """스키마에 근거가 없는 집계 기준 중 인구통계·속성 분류로 보이는 값을 조회 불가 사유로 등록한다."""

    plan = output.analysis_plan
    if not plan.group_by:
        return output
    # 현재 group_by를 비운 계획으로 실제 스키마에 근거한 후보만 구한다.
    # 현재 선택값이 잘못됐더라도 카탈로그에 다시 포함돼 유효한 기준으로 오인되지 않게 한다.
    bare = build_plan_option_catalog(schema_text, plan.model_copy(update={"group_by": []}))
    if not bare.group_by:
        return output
    grounded = set()
    for option in bare.group_by:
        grounded.add(option.value.strip().casefold())
        grounded.add(option.label.strip().removesuffix("별").casefold())
    already = {condition.reason for condition in output.infeasible}
    for dimension in list(plan.group_by):
        text = str(dimension).strip()
        if not text or text.casefold() in grounded or text.casefold().removesuffix("_id") in grounded:
            continue
        if not _UNGROUNDED_DIMENSION_HINT.search(text):
            continue
        reason = f"'{text}' 기준으로 나눌 수 있는 정보가 현재 데이터에 없습니다."
        if reason in already:
            continue
        output.infeasible.append(InfeasibleCondition(field_path="group_by", label=text[:200], reason=reason))
        already.add(reason)
    return output


_CORE_FIELD_PATHS = ("date_range", "event_types", "metric.kind", "group_by")


def _cap_primary_controls(
    blocks: list[UiBlock], plan: AnalysisPlan, *, limit: int = 3
) -> list[UiBlock]:
    """확인이 필요한 주요 입력은 유지하면서 기본 한도를 넘는 나머지 블록을 고급 영역으로 이동한다."""

    missing = set(compute_missing_fields(plan, blocks))

    def must_ask(block: UiBlock) -> bool:
        """필수값이 없거나 메타데이터가 누락·확인 필요 상태인 블록인지 판단한다."""

        path = block.field_path or block.key
        if path in missing:
            return True
        root = str(path).split(".", 1)[0].split("[", 1)[0]
        meta = plan.field_metadata.get(path) or plan.field_metadata.get(root)
        return bool(meta and meta.status in {"missing", "needs_confirmation"})

    def sort_key(entry: tuple[int, UiBlock]) -> tuple[int, int]:
        """주요 입력 중 핵심 필드가 먼저 오도록 우선순위를 정하고 기존 순서를 유지한다."""

        index, block = entry
        path = block.field_path or block.key
        return (1 if path in _CORE_FIELD_PATHS else 2), index

    primary = [(index, block) for index, block in enumerate(blocks) if block.section == "primary"]
    forced = {index for index, block in primary if must_ask(block)}
    optional = sorted((entry for entry in primary if entry[0] not in forced), key=sort_key)
    keep = set(forced)
    for index, _block in optional[: max(0, limit - len(forced))]:
        keep.add(index)

    return [
        block.model_copy(update={"section": "advanced"})
        if block.section == "primary" and index not in keep
        else block
        for index, block in enumerate(blocks)
    ]


def _hydrate_block_options(block: UiBlock, catalog: Any) -> UiBlock:
    """블록 경로에 맞는 카탈로그 선택지를 보충하고 출력 형식 블록을 고급 영역으로 배치한다."""

    path = block.field_path or block.key
    updates: dict[str, Any] = {}
    if path == "output.view":
        updates["section"] = "advanced"
    available: list[UiOption] = []
    if path == "event_types":
        available = catalog.event_types
    elif path == "group_by":
        available = catalog.group_by
    elif path == "metric.kind":
        available = _METRIC_KIND_OPTIONS
    elif path in {"metric.field", "metric.numerator", "metric.denominator"}:
        available = catalog.count_fields
    elif path == "comparison":
        available = catalog.comparisons
    elif path == "output.view":
        available = OUTPUT_VIEW_OPTIONS
    if available:
        updates["options"] = merge_options(block.options, available)
    return block.model_copy(update=updates) if updates else block


def _bounded_unique_controls(blocks: list[UiBlock], *, limit: int) -> list[UiBlock]:
    """중복 필드와 키를 정리하고 핵심 편집 항목을 우선해 지정 개수 이내의 UI 블록을 선택한다."""

    unique: list[UiBlock] = []
    seen_paths: set[str] = set()
    seen_keys: set[str] = set()
    for block in blocks:
        path = block.field_path
        if path and path in seen_paths:
            continue
        key = block.key
        if key in seen_keys:
            suffix = 2
            while f"{key}_{suffix}" in seen_keys:
                suffix += 1
            block = block.model_copy(update={"key": f"{key}_{suffix}"})
        if path:
            seen_paths.add(path)
        seen_keys.add(block.key)
        unique.append(block)
    if len(unique) <= limit:
        return unique

    core_paths = {
        "date_range", "event_types", "metric.kind", "metric.field",
        "group_by", "comparison", "output.view",
    }

    def priority(item: tuple[int, UiBlock]) -> tuple[int, int]:
        """핵심 필드·기타 입력·안내 블록 순으로 선택 우선순위를 부여한다."""

        index, block = item
        path = block.field_path or block.key
        if path in core_paths:
            return 0, index
        if block.type not in {"review", "notice", "text"}:
            return 1, index
        return 2, index

    selected = sorted(sorted(enumerate(unique), key=priority)[:limit], key=lambda item: item[0])
    return [block for _, block in selected]
