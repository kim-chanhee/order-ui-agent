"""실제 데이터베이스에서 질문과 관련된 계획 수립용 스키마 맥락을 수집한다.

주요 기능:
    - 질문 관련 테이블을 검색하고 관계를 최대 두 단계 확장한다.
    - 테이블 구조, 값 분포, 의미 정보, 관계와 질문 관련 별칭을 묶는다.
    - 일반 샘플 행과 CREATE TABLE 문을 제외하고 텍스트 길이를 제한한다.
    - 선택한 테이블 목록, 스키마 텍스트와 스키마 식별값을 함께 반환한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.execution.semantic_aliases import alias_grounding_context
from app.execution.schema_tools import (
    discover_relationships,
    get_semantic_context,
    get_table_schema,
    retrieve_relevant_schema,
)


@dataclass(frozen=True)
class PlannerSchemaContext:
    """계획 수립에 사용할 테이블 목록, 스키마 설명과 스키마 식별값을 담는다."""

    table_names: tuple[str, ...]
    text: str
    schema_fingerprint: str


def build_planner_schema_context(question: str, *, top_k: int = 8) -> PlannerSchemaContext:
    """질문 관련 테이블과 관계를 탐색하고 스키마·의미·별칭을 길이가 제한된 맥락으로 묶는다."""

    retrieval = retrieve_relevant_schema(question, top_k=top_k)
    names = list(retrieval.table_names[:8])
    if not names:
        return PlannerSchemaContext((), retrieval.context, retrieval.schema_fingerprint)
    relationship_parts: list[str] = []
    relevance = {
        candidate.table_name: candidate.score
        for candidate in getattr(retrieval, "candidates", ())
    }
    frontier = list(names)
    for _hop in range(2):
        if not frontier or len(names) >= 16:
            break
        relationships = str(discover_relationships.invoke({"table_names": ",".join(frontier)}))
        relationship_parts.append(relationships)
        discovered = _relationship_tables(relationships)
        discovered.sort(key=lambda name: (
            -(relevance.get(name, 0) + _namespace_affinity(name, frontier)),
            name,
        ))
        frontier = []
        added_this_hop = 0
        for name in discovered:
            if name in names:
                continue
            names.append(name)
            frontier.append(name)
            added_this_hop += 1
            if len(names) >= 16 or added_this_hop >= 4:
                break
    names_tuple = tuple(names)
    table_list = ",".join(names_tuple)
    physical_parts = [
        _compact_schema_text(str(get_table_schema.invoke({"table_names": name, "question": question})))[:1700]
        for name in names_tuple
    ]
    semantic = str(get_semantic_context.invoke({"table_names": table_list}))
    bounded_relationships = str(discover_relationships.invoke({
        "table_names": table_list,
        "candidate_table_names": table_list,
    })) if len(names_tuple) > 1 else ""
    aliases = alias_grounding_context(question)
    text = "\n\n".join(
        part for part in (
            retrieval.context,
            f"Question-scoped canonical value aliases:\n{aliases}" if aliases else "",
            *physical_parts,
            *relationship_parts,
            bounded_relationships[:4500],
            semantic[:3500],
        ) if part
    )[:38000]
    return PlannerSchemaContext(names_tuple, text, retrieval.schema_fingerprint)


def _relationship_tables(value: str) -> list[str]:
    """관계 설명의 원본·대상 테이블 이름을 추출하고 순서대로 중복 없이 반환한다."""

    tables: list[str] = []
    for source, target in re.findall(
        r"^-\s+([A-Za-z_][A-Za-z0-9_]*)\.[^\s]+\s+->\s+([A-Za-z_][A-Za-z0-9_]*)\.",
        value,
        re.MULTILINE,
    ):
        for table in (source, target):
            if table not in tables:
                tables.append(table)
    return tables


def _namespace_affinity(candidate: str, frontier: list[str]) -> float:
    """관계 확장 후보가 현재 테이블들과 같은 이름 접두사를 쓰면 우선순위 점수를 부여한다."""

    prefix = candidate.split("_", 1)[0]
    if any(source == prefix or source.split("_", 1)[0] == prefix for source in frontier):
        return 5.0
    return 0.0


def _compact_schema_text(value: str) -> str:
    """일반 샘플 행과 테이블 생성문을 제외하고 질문 관련 샘플·컬럼·분포 정보를 제한 길이로 유지한다."""

    lines: list[str] = []
    skipping_sample = False
    for raw in value.splitlines():
        line = raw.strip()
        if line == "Question-relevant sample rows:":
            skipping_sample = False
            lines.append(raw)
            continue
        if line == "Stable sample rows:":
            skipping_sample = True
            continue
        if skipping_sample and line.startswith("- sample "):
            continue
        if skipping_sample and not line.startswith("- sample "):
            skipping_sample = False
        if line.startswith("CREATE TABLE SQL:"):
            continue
        if line.upper().startswith("CREATE TABLE"):
            continue
        lines.append(raw)
    return "\n".join(lines)[:5500]
