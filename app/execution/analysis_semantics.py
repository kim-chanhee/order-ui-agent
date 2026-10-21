"""스키마만으로 알기 어려운 업무 의미 설정을 읽고 SQL에 적용한다.

Data/docs/analysis_semantics.json 또는 ANALYSIS_SEMANTICS_PATH에서 설정을 읽는다.
기간 기준, 엔터티 생애주기, 식별자·속성 역할, 관계 범위의 의미 근거를 제공한다.
상대 기간의 모집단과 직접 연결 범위가 설정된 업무 조건을 따르는지 SQL을 검사한다.
이 파일은 텍스트·CTE 구조 중심 검사를 하고 sql_contract는 AST 기반 조건 검사도 수행한다.
설정은 캐시하며 파일이 없거나 JSON을 읽지 못하면 빈 설정을 사용한다.
물리 테이블·컬럼의 실제 존재 여부는 별도의 라이브 스키마 확인이 필요하다.
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.data.database import PROJECT_ROOT


SEMANTICS_ENV = "ANALYSIS_SEMANTICS_PATH"
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _contains_term(text: str, term: str) -> bool:
    """설정 용어가 독립된 단어 경계로 등장하는지 확인한다.

    direct가 direction 일부에 포함된 경우처럼 단순 부분 문자열 검색의 잘못된 일치를 줄인다.
    """

    if not term:
        return False
    return re.search(rf"\b{re.escape(term)}\b", text) is not None


def analysis_semantics_path() -> Path:
    """환경 변수 또는 기본 Data/docs 위치에서 업무 의미 설정 파일 경로를 선택한다.

    홈 축약을 확장하고 상대 경로는 프로젝트 루트 기준으로 해석한다.
    """

    configured = os.environ.get(SEMANTICS_ENV, "").strip()
    path = Path(configured).expanduser() if configured else PROJECT_ROOT / "Data" / "docs" / "analysis_semantics.json"
    return path if path.is_absolute() else PROJECT_ROOT / path


@lru_cache(maxsize=8)
def _load(path_text: str) -> dict[str, Any]:
    """주어진 경로의 JSON 객체를 읽고 경로별로 캐시한다.

    읽기·JSON 해석에 실패하거나 최상위 값이 객체가 아니면 빈 딕셔너리를 반환한다.
    """

    try:
        payload = json.loads(Path(path_text).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def load_analysis_semantics() -> dict[str, Any]:
    """현재 설정 경로를 절대 경로로 정리해 캐시된 의미 설정을 반환한다.

    파일 해석과 실패 처리는 _load에 맡기는 공통 진입점이다.
    """

    return _load(str(analysis_semantics_path().resolve()))


def timeline_anchor() -> tuple[str, str] | None:
    """의미 설정에서 데이터 시간축 기준의 테이블·컬럼을 추출한다.

    두 이름이 허용된 식별자 형식일 때만 튜플로 반환하고, 설정이 없거나 잘못됐으면 None을 반환한다.
    """

    raw = load_analysis_semantics().get("timeline_anchor")
    if not isinstance(raw, dict):
        return None
    table, field = str(raw.get("table") or ""), str(raw.get("field") or "")
    if not (_IDENTIFIER.fullmatch(table) and _IDENTIFIER.fullmatch(field)):
        return None
    return table, field


def semantic_execution_context() -> str:
    """의미 설정을 LLM에 제공할 보조 설명 JSON 문자열로 변환한다.

    설정이 없으면 빈 문자열을 반환하고 있으면 길이를 제한해 물리 이름을 확인하라는 안내와 함께 제공한다.
    """

    payload = load_analysis_semantics()
    if not payload:
        return ""
    return "Schema-adjacent analysis semantics (advisory; verify physical names):\n" + json.dumps(
        payload, ensure_ascii=False, indent=2
    )[:10000]


def validate_configured_semantics_sql(
    confirmed_plan: Any | None,
    sql: str,
    *,
    temporal_context: Any | None = None,
) -> str:
    """계획의 기간·대상·관계 의미에 대응하는 업무 조건이 SQL에 있는지 검사한다.

    상대 기간 모집단의 생성 조건, 직접 이벤트 연결과 소속 관계, 기간 모집단과 이벤트의 연결을 확인한다.
    위반 시 ValueError를 발생시키고 검사할 계획이 없거나 통과하면 원래 SQL을 반환한다.
    """

    if confirmed_plan is None:
        return sql
    plan = confirmed_plan.model_dump(mode="json") if hasattr(confirmed_plan, "model_dump") else confirmed_plan
    if not isinstance(plan, dict):
        return sql
    payload = load_analysis_semantics()
    semantic_text = json.dumps(plan, ensure_ascii=False).casefold()
    sql_text = sql.casefold()
    mode = (
        temporal_context.model_dump(mode="json").get("mode")
        if hasattr(temporal_context, "model_dump")
        else (temporal_context or {}).get("mode") if isinstance(temporal_context, dict) else None
    )
    if mode in {"relative", "preset"}:
        for entity, raw in (payload.get("entity_lifecycles") or {}).items():
            if not isinstance(raw, dict):
                continue
            terms = [str(entity), *[str(value) for value in raw.get("semantic_terms", [])]]
            table = str(raw.get("table") or "")
            field = str(raw.get("creation_field") or "")
            value = str(raw.get("creation_value") or "")
            if not all(_IDENTIFIER.fullmatch(item) for item in (table, field)) or not value:
                continue
            if not any(_contains_term(semantic_text, term.casefold()) for term in terms) or table.casefold() not in sql_text:
                continue
            predicate = re.compile(
                rf"(?:[a-z_][a-z0-9_]*\s*\.\s*)?{re.escape(field.casefold())}\s*=\s*['\"]{re.escape(value.casefold())}['\"]"
            )
            if not predicate.search(sql_text):
                raise ValueError(
                    f"relative {entity} population must use configured creation semantics "
                    f"{table}.{field} = {value!r}, not arbitrary lifecycle events"
                )

    direct_terms = [str(value).casefold() for value in payload.get("direct_scope_terms", [])]
    selected_parent = any(
        any(_contains_term(semantic_text, str(term).casefold()) for term in raw.get("semantic_terms", []))
        for raw in (payload.get("entity_lifecycles") or {}).values()
        if isinstance(raw, dict)
    )
    if selected_parent and any(_contains_term(semantic_text, term) for term in direct_terms):
        for scope in payload.get("relationship_scopes", []):
            if not isinstance(scope, dict):
                continue
            event_table = str(scope.get("event_object_table") or "")
            event_qualifier_field = str(scope.get("object_qualifier_field") or "")
            event_qualifier_value = str(scope.get("object_qualifier_value") or "")
            membership_table = str(scope.get("membership_table") or "")
            qualifier_field = str(scope.get("membership_qualifier_field") or "")
            qualifier_value = str(scope.get("membership_qualifier_value") or "")
            required = [event_table, event_qualifier_field, membership_table, qualifier_field]
            if not all(_IDENTIFIER.fullmatch(item) for item in required) or not event_qualifier_value or not qualifier_value:
                continue
            event_qualifier = re.compile(
                rf"(?:[a-z_][a-z0-9_]*\s*\.\s*)?{re.escape(event_qualifier_field.casefold())}\s*=\s*['\"]{re.escape(event_qualifier_value.casefold())}['\"]"
            )
            qualifier = re.compile(
                rf"(?:[a-z_][a-z0-9_]*\s*\.\s*)?{re.escape(qualifier_field.casefold())}\s*=\s*['\"]{re.escape(qualifier_value.casefold())}['\"]"
            )
            if event_table.casefold() not in sql_text or not event_qualifier.search(sql_text):
                raise ValueError(
                    "direct event-linked entities must use configured direct association "
                    f"{event_table} ({event_qualifier_field}={event_qualifier_value!r})"
                )
            if membership_table.casefold() not in sql_text or not qualifier.search(sql_text):
                raise ValueError(
                    "direct event-linked entities must be intersected with configured membership "
                    f"scope {membership_table} ({qualifier_field}={qualifier_value!r})"
                )
            lifecycle_id_fields = [
                str(raw.get("id_field") or "")
                for raw in (payload.get("entity_lifecycles") or {}).values()
                if isinstance(raw, dict) and _IDENTIFIER.fullmatch(str(raw.get("id_field") or ""))
            ]
            event_values = [str(value).casefold() for value in plan.get("event_types", []) if str(value)]
            scoped_event_body_found = False
            for body in _cte_bodies(sql_text):
                if "event_id" not in body or not any(value in body for value in event_values):
                    continue
                for id_field in lifecycle_id_fields:
                    qualified_equality = re.compile(
                        rf"[a-z_][a-z0-9_]*\s*\.\s*{re.escape(id_field.casefold())}\s*=\s*"
                        rf"[a-z_][a-z0-9_]*\s*\.\s*{re.escape(id_field.casefold())}"
                    )
                    population_subquery = re.compile(
                        rf"(?:[a-z_][a-z0-9_]*\s*\.\s*)?{re.escape(id_field.casefold())}\s+in\s*\(\s*select\s+"
                        rf"(?:[a-z_][a-z0-9_]*\s*\.\s*)?{re.escape(id_field.casefold())}"
                    )
                    if qualified_equality.search(body) or population_subquery.search(body):
                        scoped_event_body_found = True
                        break
            if event_values and not scoped_event_body_found:
                raise ValueError(
                    "direct event rows must be intersected by the configured parent identifier "
                    "with the same period-qualified population used by the selected metric"
                )
    return sql


def _cte_bodies(sql: str) -> list[str]:
    """SQL에서 이름 AS (...) 형태의 공통 테이블 식 본문을 추출한다.

    따옴표와 괄호 깊이를 추적해 닫는 괄호까지 찾고, 업무 관계 범위 검사에 사용할 본문 목록을 반환한다.
    """

    bodies: list[str] = []
    for match in re.finditer(r"\b[a-z_][a-z0-9_]*\s+as\s*\(", sql, re.IGNORECASE):
        opening = match.end() - 1
        depth = 0
        quote: str | None = None
        for index in range(opening, len(sql)):
            char = sql[index]
            if quote:
                if char == quote:
                    quote = None
                continue
            if char in {"'", '"', "`"}:
                quote = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    bodies.append(sql[opening + 1:index])
                    break
    return bodies
