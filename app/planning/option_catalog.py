"""스키마와 현재 분석 계획에 근거한 확인 화면 선택지를 만든다.

주요 기능:
    - 스키마 텍스트에서 컬럼과 이벤트 값을 추출해 집계 기준·건수 단위를 구성한다.
    - 현재 선택값을 보존하면서 카탈로그 선택지를 보충하고 중복을 제거한다.
    - 이벤트·집계 기준·건수 단위를 화면용 이름으로 변환한다.
    - 비교 방식과 결과 표시 형식에 사용할 기본 선택지를 제공한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.execution.semantic_aliases import canonical_value_labels
from app.execution.analysis_semantics import load_analysis_semantics, declared_identifier_fields
from app.planning.analysis_models import AnalysisPlan
from app.planning.ui_models import UiOption


_LOW_CARDINALITY_VALUE = re.compile(r"(?:^|,\s*)(.+?)\s+\(\d+\)(?=,|$)")
_PROFILE_VALUE_LINE = re.compile(r"^\s*-\s+(event_type|ocel_type):\s+(.+)$")
_TABLE_HEADER_LINE = re.compile(r"^TABLE:\s+(\S+)\s*$")
_COLUMN_LINE = re.compile(
    r"^\s*-\s+([A-Za-z_][A-Za-z0-9_]*)\s+(?:TEXT|NUM|INTEGER|INT|REAL|FLOAT|DOUBLE|DATE|DATETIME|TIMESTAMP|VARCHAR|\(no declared type\))",
    re.MULTILINE | re.IGNORECASE,
)
_TABLE_SIGNATURE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\(([^\n]+)\)$", re.MULTILINE)

_DIMENSION_LABELS = {
    "customer": "고객별",
    "courier": "배송 기사별",
    "shipper": "배송 기사별",
    "employee": "직원별",
    "product": "상품별",
    "item": "물품별",
    "order": "주문별",
    "package": "패키지별",
    "event": "이벤트별",
    "event_type": "이벤트 유형별",
    "status": "상태별",
    "day": "일자별",
    "month": "월별",
    "year": "연도별",
}
_COUNT_FIELD_LABELS = {
    "event_id": "이벤트 발생 기준",
    "order_id": "주문 기준",
    "item_id": "물품 기준",
    "product_id": "상품 기준",
    "package_id": "패키지 기준",
    "customer_id": "고객 기준",
    "courier_id": "배송 기사 기준",
    "shipper_id": "배송 기사 기준",
    "employee_id": "직원 기준",
}

COMPARISON_OPTIONS = [
    UiOption(value="event_vs_event", label="이벤트 간 비교", description="두 이벤트나 상태를 같은 기준으로 비교합니다."),
    UiOption(value="breakdown", label="항목별 분포", description="선택한 대상을 유형별로 나눠 봅니다."),
    UiOption(value="none", label="비교 없음", description="선택한 대상만 조회합니다."),
]
OUTPUT_VIEW_OPTIONS = [
    UiOption(value="summary", label="요약"),
    UiOption(value="table", label="표"),
    UiOption(value="chart", label="차트"),
    UiOption(value="table_and_chart", label="표와 차트"),
]


@dataclass(frozen=True)
class PlanOptionCatalog:
    """이벤트 유형·집계 기준·건수 단위·비교 방식의 화면 선택지를 묶는다."""

    event_types: list[UiOption]
    group_by: list[UiOption]
    count_fields: list[UiOption]
    comparisons: list[UiOption]
    metric_kinds: list[UiOption] = field(default_factory=list)
    numeric_fields: list[UiOption] = field(default_factory=list)
    semantic_metrics: dict = field(default_factory=dict)
    schema: dict = field(default_factory=dict)


def build_plan_option_catalog(schema_text: str, plan: AnalysisPlan) -> PlanOptionCatalog:
    """스키마에서 확인한 값과 현재 계획의 선택값으로 이벤트·집계 기준·건수 단위·비교 선택지를 만든다."""

    schema = schema_catalog(schema_text)
    columns = list(dict.fromkeys(column for table in schema.values() for column in table)) or _schema_columns(schema_text)
    definitions = available_semantic_metrics(schema)
    metric = plan.metric
    scope_tables = []
    if metric and metric.semantic_id in definitions:
        scope_tables = [definitions[metric.semantic_id]['table']]
    elif metric and metric.field:
        scope_tables = [name for name, fields in schema.items() if metric.field in fields]
    reachable = reachable_columns(schema, scope_tables) if scope_tables else set(columns)
    group_candidates = _group_candidates([c for c in columns if c in reachable])
    # SQLite text dimensions and configured identifiers work across domains;
    # do not limit grouping/counting to logistics-specific entity names.
    identifiers = declared_identifier_fields()
    text_dimensions = [c for fields in schema.values() for c, dtype in fields.items()
                       if c in reachable and re.search(r'TEXT|CHAR|BOOL', dtype, re.I)
                       and not is_time_field(c, dtype)]
    # Display names are valid dimensions too, provided they exist in the
    # reachable schema and the domain configuration declares their role.
    display_names = set(load_analysis_semantics().get('attribute_roles', {}).get('display_name', []))
    group_candidates = list(dict.fromkeys([
        *group_candidates, *text_dimensions,
        *[c for c in columns if c in reachable and c in display_names],
    ]))
    # A temporal bucket is supported only when a real date/time column exists.
    time_columns = {c for fields in schema.values() for c,t in fields.items() if is_time_field(c,t)} & reachable
    if time_columns:
        group_candidates = list(dict.fromkeys([*group_candidates, 'day', 'month', 'year']))
    else:
        group_candidates = [c for c in group_candidates if c != 'day']
    if metric and metric.semantic_id in definitions:
        group_candidates = [c for c in group_candidates if c in definitions[metric.semantic_id]["group_by"]]
    groups = [UiOption(value=c, label=_dimension_label(c)) for c in group_candidates]
    numeric = [c for fields in schema.values() for c,t in fields.items()
               if c in reachable and re.search(r'INT|REAL|NUM|FLOAT|DOUBLE|DECIMAL',t,re.I)
               and not is_time_field(c,t) and c not in identifiers and c != 'id' and not c.endswith('_id')]
    numeric = list(dict.fromkeys(numeric))
    counts = [c for c in columns if c in reachable and
              (c in identifiers or c in {'id', 'ocel_id'} or c.endswith('_id'))]
    kinds = ['rows', 'count']
    if any(d['kind']=='ratio' for d in definitions.values()):
        kinds.append('ratio')
    if numeric:
        kinds.extend(['sum','avg','min','max'])
    labels = {'rows':'상세 목록','count':'건수','ratio':'비율','sum':'합계','avg':'평균','min':'최솟값','max':'최댓값'}
    return PlanOptionCatalog(
        event_types=[UiOption(value=v,label=_event_label(v)) for v in _event_values(schema_text)],
        group_by=groups,
        count_fields=[UiOption(value=c,label=_count_field_label(c)) for c in counts],
        comparisons=list(COMPARISON_OPTIONS),
        metric_kinds=[UiOption(value=k,label=labels[k]) for k in kinds],
        numeric_fields=[UiOption(value=c,label=c) for c in numeric],
        semantic_metrics=definitions, schema=schema,
    )


def is_time_field(name: str, dtype: str) -> bool:
    return bool(re.search(r'DATE|TIME', dtype, re.I) or name.endswith(('_date','_time','_at')))


def schema_catalog(text: str) -> dict[str, dict[str, str]]:
    """Extract table-local columns, preserving types for numeric/temporal grounding."""
    result = {}
    current = None
    for line in text.splitlines():
        header = _TABLE_HEADER_LINE.match(line)
        if header:
            current = header.group(1)
            result.setdefault(current,{})
        signature = re.fullmatch(r'([A-Za-z_][A-Za-z0-9_]*)\((.*)\)',line.strip())
        if signature:
            result.setdefault(signature.group(1),{}).update({part.strip().split()[0]: ' '.join(part.strip().split()[1:]) for part in signature.group(2).split(',') if part.strip()})
        match = re.match(r'\s*-\s+([A-Za-z_][A-Za-z0-9_]*)\s+(TEXT|NUM|INTEGER|INT|REAL|FLOAT|DOUBLE|DATE|DATETIME|TIMESTAMP|VARCHAR|\(no declared type\))',line,re.I)
        if match and current:
            result[current][match.group(1)] = match.group(2)
    return result


def reachable_columns(schema: dict, start_tables: list[str]) -> set[str]:
    """Conservative joins: common typed business identifiers, never generic ocel_id."""
    selected = set(start_tables)
    config = load_analysis_semantics()
    ids = set(_COUNT_FIELD_LABELS) | {field for entity in config.get('entity_roles', {}).values()
                                    for field in entity.get('identifier_fields', [])}
    edges = config.get('entity_relationships', [])
    while True:
        columns = {c for t in selected for c in schema.get(t,{})}
        more = {t for t,fields in schema.items() if (set(fields) & columns & ids)}
        for edge in edges:
            source, target = edge.get('table'), edge.get('target_table')
            if (source in schema and target in schema
                and edge.get('source_field') in schema[source] and edge.get('target_field') in schema[target]
                and selected & {source, target}):
                more.update({source, target})
        if more <= selected:
            return columns
        selected |= more


def available_semantic_metrics(schema: dict) -> dict:
    available = {}
    for name, definition in load_analysis_semantics().get('semantic_metrics',{}).items():
        table = definition.get('table')
        if definition.get('kind') not in {'ratio','count'} or table not in schema:
            continue
        if definition.get('population'):
            sources=[definition['population'], definition['subset']]
            if not all(source['table'] in schema and
                       {source['key'],source['time_field'],*source.get('filters',{})} <= set(schema[source['table']])
                       for source in sources):
                continue
        required = {definition.get('field'), definition.get('event_field'), definition.get('time_field')}
        if required <= set(schema[table]):
            available[name] = definition
    return available


def catalog_snapshot(catalog: PlanOptionCatalog) -> dict:
    return {name: [o.model_dump(mode='json') for o in getattr(catalog,name)]
            for name in ('event_types','group_by','count_fields','metric_kinds','numeric_fields')} | {
        'semantic_metrics':catalog.semantic_metrics, 'schema':catalog.schema,
    }


def _schema_columns(text: str) -> list[str]:
    """컬럼 설명과 테이블 요약 형식에서 컬럼 이름을 추출해 중복 없이 반환한다."""

    values = list(_COLUMN_LINE.findall(text or ""))
    for signature in _TABLE_SIGNATURE.findall(text or ""):
        for raw_column in signature.split(","):
            name = raw_column.strip().split(" ", 1)[0]
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                values.append(name)
    return list(dict.fromkeys(values))


def _event_values(text: str) -> list[str]:
    # ocel_type의 값 분포는 이벤트 테이블과 객체 테이블에 모두 존재한다.
    # 이벤트 테이블에는 배송 실패 같은 이벤트 유형이, 객체 테이블에는
    # 물품·주문 같은 객체 유형이 있으므로 현재 TABLE 블록을 기준으로 구분한다.
    # 객체 유형이 이벤트 필터의 선택지에 섞이지 않도록 객체 테이블을 제외한다.
    """객체 테이블을 제외한 값 분포에서 이벤트 유형 값을 추출하고 중복을 제거한다."""

    values: list[str] = []
    current_table = ""
    for line in (text or "").splitlines():
        header = _TABLE_HEADER_LINE.match(line)
        if header:
            current_table = header.group(1).lower()
            continue
        if current_table.startswith("object"):
            continue
        match = _PROFILE_VALUE_LINE.match(line)
        if not match:
            continue
        values.extend(item.group(1).strip() for item in _LOW_CARDINALITY_VALUE.finditer(match.group(2)))
    return list(dict.fromkeys(value for value in values if value))


def _group_candidates(columns: list[str]) -> list[str]:
    """컬럼 이름에서 지원하는 대상 ID·이벤트 유형·날짜별 집계 기준 후보를 찾는다."""

    candidates: list[str] = []
    for column in columns:
        lowered = column.lower()
        root = lowered.removesuffix("_id")
        if lowered == "event_type":
            candidates.append(lowered)
        elif lowered.endswith("_id") and root != "event":
            candidates.append(lowered)
        elif lowered.endswith(("_date", "_time", "_at")) and "day" not in candidates:
            candidates.append("day")
    return list(dict.fromkeys(candidates))


def _event_label(value: str) -> str:
    """이벤트 값의 표준 표시 이름을 찾고 없으면 밑줄을 공백으로 바꿔 반환한다."""

    label = canonical_value_labels().get(value.lower())
    return label or value.replace("_", " ")


def _dimension_label(value: str) -> str:
    """집계 기준 컬럼을 화면용 이름으로 변환하고 알 수 없는 값에는 별 접미사를 붙인다."""

    lowered = value.lower()
    root = lowered.removesuffix("_id")
    return _DIMENSION_LABELS.get(lowered) or _DIMENSION_LABELS.get(root) or f"{value}별"


def _count_field_label(value: str) -> str:
    """건수 집계 컬럼을 화면용 기준 이름으로 변환한다."""

    return _COUNT_FIELD_LABELS.get(value.lower(), f"{value} 기준")
