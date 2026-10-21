"""실제 SQLite 스키마와 데이터 특성을 읽기 전용으로 탐색한다.

list_tables/get_table_schema/get_semantic_context/discover_relationships는 LLM용 도구다.
retrieve_relevant_schema는 LLM 없이 질문·컬럼·값·의미 문서의 관련도를 계산해
초기 테이블 후보를 고르고, 필요한 경우 후보 사이의 연결 테이블을 보충한다.
샘플 값·식별자 고유 개수·시간 범위는 집계 단위와 필터를 판단할 근거로 제공한다.
관계 후보는 외래 키·식별자 이름·일부 실제 값 중첩으로 추정하므로 의미 확정과는 다르다.
의미 문서는 보조 자료이며 실제 테이블·컬럼 확인은 라이브 스키마가 기준이다.
스키마 fingerprint는 현재 DB 구조를 식별해 관련 캐시를 구분하는 데 쓰인다.
"""

from __future__ import annotations

import os
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from difflib import SequenceMatcher
from hashlib import sha256
from pathlib import Path
from typing import Iterable

from langchain_core.tools import tool

from app.data.database import DEFAULT_DB_PATH
from app.execution.semantic_aliases import canonical_values_for_text
from app.execution.analysis_semantics import semantic_execution_context
from app.execution.sql_safety import create_read_only_connection


_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+|[가-힣]{2,}")
_FOLLOWUP_MARKERS = (
    "previous results from this thread",
    "그 ",
    "이전 ",
    "앞 ",
    "해당 ",
)


@dataclass(frozen=True)
class SchemaCandidate:
    """테이블별 검색 점수와 일치 단어·컬럼·값을 보관하는 불변 결과 객체다.

    후보 정렬과 검색 근거 설명에 어휘·유사도·값 점수를 함께 사용한다.
    """

    table_name: str
    score: float
    matched_terms: tuple[str, ...] = ()
    matched_columns: tuple[str, ...] = ()
    matched_values: tuple[str, ...] = ()
    lexical_score: float = 0.0
    fuzzy_score: float = 0.0
    value_score: float = 0.0


@dataclass(frozen=True)
class SchemaRetrievalResult:
    """초기 선택 테이블·전체 후보·검색 설명·스키마 fingerprint를 묶는다.

    계획 생성기와 SQL 에이전트가 같은 스키마 검색 결과를 재사용할 수 있게 한다.
    """

    table_names: tuple[str, ...]
    candidates: tuple[SchemaCandidate, ...]
    context: str
    schema_fingerprint: str


@tool
def list_tables() -> str:
    """List user tables and data-derived ranges for likely temporal columns."""

    # 현재 DB의 사용자 테이블·뷰 목록과 분석용 테이블의 컬럼·시간 범위를 요약한다.
    # 첫 줄은 기존 호출자가 분리할 수 있도록 쉼표로 연결한 이름 목록을 유지한다.

    with closing(create_read_only_connection(DEFAULT_DB_PATH)) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view') "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        names = [row[0] for row in rows]
        temporal_ranges = _discover_temporal_ranges(conn, names)
        analysis_tables = [name for name in names if name.lower().startswith("analysis_")]
        analysis_profiles = {
            table: ", ".join(
                str(column[1])
                for column in conn.execute(f"PRAGMA table_info({_quote(table)})").fetchall()
            )
            for table in analysis_tables
        }
    if not names:
        return "(no user tables)"
    # Keep the first line compatible with callers that split the historical
    # comma-separated response, then append richer runtime metadata.
    lines = [", ".join(names)]
    if analysis_tables:
        lines.append("Analysis-oriented tables discovered (inspect suitable candidates before raw tables):")
        for table in analysis_tables:
            lines.append(f"- {table}: {analysis_profiles[table]}")
    if temporal_ranges:
        lines.append("Data-derived temporal ranges (use these instead of the machine clock):")
        lines.extend(f"- {item}" for item in temporal_ranges)
    return "\n".join(lines)


def retrieve_relevant_schema(
    question: str,
    *,
    cached_tables: Iterable[str] = (),
    top_k: int | None = None,
) -> SchemaRetrievalResult:
    """질문·별칭·라이브 컬럼·샘플 값·의미 문서의 관련도로 초기 테이블 후보를 고른다.

    후속 질문에서는 이전 테이블을 고려하고 최상위 후보 사이에 필요한 연결 테이블을 보충한다.
    LLM 호출 없이 테이블 목록·점수 근거·스키마 fingerprint를 반환한다.
    """

    requested_k = top_k or int(os.environ.get("SCHEMA_RETRIEVAL_TOP_K", "3"))
    bounded_k = max(1, min(requested_k, 8))
    current_question = _current_question(question)
    canonical_terms = [
        value
        for values in canonical_values_for_text(current_question).values()
        for value in values
    ]
    if canonical_terms:
        current_question = f"{current_question} {' '.join(canonical_terms)}"
    semantic_text = _read_semantic_text()
    cached = list(
        dict.fromkeys(
            str(table).strip()
            for table in cached_tables
            if str(table).strip()
        )
    )

    with closing(create_read_only_connection(DEFAULT_DB_PATH)) as conn:
        schema_objects = [
            (str(row[0]), str(row[1]))
            for row in conn.execute(
                "SELECT name, type FROM sqlite_master "
                "WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
        table_names = [name for name, _object_type in schema_objects]
        object_types = {name: object_type for name, object_type in schema_objects}
        candidates: list[SchemaCandidate] = []
        for table in table_names:
            document, columns, values = _retrieval_features(conn, table, semantic_text)
            lexical_score, fuzzy_score, matched = _schema_match_score(current_question, table, document)
            matched_columns = _matched_schema_items(current_question, columns)
            matched_values = _matched_schema_items(current_question, values, value_mode=True)
            value_score = len(matched_values) * 5.0
            score = lexical_score + fuzzy_score + value_score + len(matched_columns) * 2.5
            if table.lower().startswith("analysis_") and score > 0:
                score += 0.35
            if object_types.get(table) == "view" and score > 0:
                # Curated views intentionally collapse ambiguous raw joins into
                # one documented business grain, so prefer them as retrieval seeds.
                score += 10.0
            if table in cached and _looks_like_followup(question):
                score += 6.0
                matched.add("previous-result table")
            candidates.append(
                SchemaCandidate(
                    table_name=table,
                    score=round(score, 3),
                    matched_terms=tuple(sorted(matched)),
                    matched_columns=tuple(matched_columns),
                    matched_values=tuple(matched_values),
                    lexical_score=round(lexical_score, 3),
                    fuzzy_score=round(fuzzy_score, 3),
                    value_score=round(value_score, 3),
                )
            )

    candidates.sort(key=lambda item: (-item.score, item.table_name))
    if candidates and not any(candidate.score > 0 for candidate in candidates):
        candidates.sort(
            key=lambda item: (
                not item.table_name.lower().startswith("analysis_"),
                item.table_name,
            )
        )

    selected: list[str] = []
    if _looks_like_followup(question):
        selected.extend(table for table in cached[:2] if table in table_names)
    target_size = min(len(table_names), bounded_k + (1 if selected else 0))
    for candidate in candidates:
        if candidate.table_name in selected:
            continue
        selected.append(candidate.table_name)
        if len(selected) >= target_size:
            break

    # Preserve the best semantic seeds and add only the shortest identifier/FK
    # bridge required to connect the two strongest tables.
    if len(selected) >= 2:
        with closing(create_read_only_connection(DEFAULT_DB_PATH)) as conn:
            graph = _schema_join_graph(conn, table_names)
        bridge = _shortest_path(graph, selected[0], selected[1])
        for table in bridge[1:-1] if bridge else ():
            if table not in selected and len(selected) < bounded_k + 2:
                selected.append(table)

    fingerprint = schema_fingerprint()
    selected_candidates = [
        candidate for candidate in candidates if candidate.table_name in selected
    ]
    selected_candidates.sort(key=lambda item: selected.index(item.table_name))
    lines = [
        "Question-time schema retrieval (seed set; expand only when required):",
        *(f"- {candidate.table_name}: score={candidate.score:g}; matched="
          f"{', '.join(candidate.matched_terms) or 'fallback'}; columns="
          f"{', '.join(candidate.matched_columns) or '-'}; values="
          f"{', '.join(candidate.matched_values) or '-'}"
          for candidate in selected_candidates),
        f"- schema fingerprint: {fingerprint}",
    ]
    return SchemaRetrievalResult(
        table_names=tuple(selected),
        candidates=tuple(candidates),
        context="\n".join(lines),
        schema_fingerprint=fingerprint,
    )


def schema_fingerprint() -> str:
    """테이블·뷰·인덱스의 정렬된 이름과 생성 SQL을 해시해 짧은 구조 식별값을 만든다.

    데이터 행 값이 아니라 스키마 구조를 식별하는 값이다.
    """

    with closing(create_read_only_connection(DEFAULT_DB_PATH)) as conn:
        rows = conn.execute(
            "SELECT name, COALESCE(sql, '') FROM sqlite_master "
            "WHERE type IN ('table', 'view', 'index') AND name NOT LIKE 'sqlite_%' "
            "ORDER BY type, name"
        ).fetchall()
    payload = "\n".join(f"{row[0]}\n{row[1]}" for row in rows)
    return sha256(payload.encode("utf-8")).hexdigest()[:16]


@tool
def get_table_schema(table_names: str, question: str = "", compact: bool = False) -> str:
    """Return live relational metadata and sample rows for SQLite tables.

    ``table_names`` is a comma-separated list. Inspect every table used by a query.
    Runtime metadata is authoritative; optional semantic documentation is advisory.
    """

    # 쉼표로 받은 테이블들의 실제 컬럼·키·인덱스·표본·데이터 특성을 읽는다.
    # 질문과 관련된 표본을 우선 제공하며 compact 옵션으로 상세 DDL 등 설명량을 줄인다.
    # SQL 생성과 검증에 사용할 스키마 설명 문자열을 반환한다.

    requested = [name.strip() for name in table_names.split(",") if name.strip()]
    if not requested:
        return "No table names were provided."
    lines: list[str] = []
    with closing(create_read_only_connection(DEFAULT_DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        for table in requested:
            try:
                columns = conn.execute(f"PRAGMA table_info({_quote(table)})").fetchall()
            except sqlite3.Error as exc:
                lines.append(f"{table}: error reading schema ({exc})")
                continue
            if not columns:
                lines.append(f"{table}: table not found")
                continue
            create_row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type IN ('table','view') AND name=?",
                (table,),
            ).fetchone()
            foreign_keys = conn.execute(f"PRAGMA foreign_key_list({_quote(table)})").fetchall()
            indexes = conn.execute(f"PRAGMA index_list({_quote(table)})").fetchall()

            column_text = ", ".join(
                f"{column[1]} {column[2]}".strip() for column in columns
            )
            lines.append(f"{table}({column_text})")
            lines.append(f"TABLE: {table}")
            _append_data_profile(lines, conn, table, columns)
            if not compact:
                lines.append("CREATE TABLE SQL:")
                lines.append(str(create_row[0]) if create_row and create_row[0] else "(not available)")
                lines.append("Columns:")
                for column in columns:
                    column_type = str(column[2] or "(no declared type)")
                    details = []
                    if column[5]:
                        details.append(f"PRIMARY KEY position {column[5]}")
                    if column[3]:
                        details.append("NOT NULL")
                    if column[4] is not None:
                        details.append(f"DEFAULT {column[4]}")
                    suffix = f" [{'; '.join(details)}]" if details else ""
                    lines.append(f"- {column[1]} {column_type}{suffix}")

            primary_keys = sorted(
                ((int(column[5]), str(column[1])) for column in columns if column[5]),
                key=lambda item: item[0],
            )
            lines.append("Primary Key:")
            lines.extend(f"- {name}" for _, name in primary_keys)
            if not primary_keys:
                lines.append("- (none declared)")

            lines.append("Foreign Keys:")
            if foreign_keys:
                for foreign_key in foreign_keys:
                    lines.append(
                        f"- {foreign_key[3]} -> {foreign_key[2]}.{foreign_key[4]} "
                        f"[ON UPDATE {foreign_key[5]}; ON DELETE {foreign_key[6]}]"
                    )
            else:
                lines.append("- (none declared)")

            if not compact:
                lines.append("Indexes:")
                if indexes:
                    for index in indexes:
                        index_name = str(index[1])
                        index_columns = conn.execute(
                            f"PRAGMA index_info({_quote(index_name)})"
                        ).fetchall()
                        names = (
                            ", ".join(str(item[2]) for item in index_columns)
                            or "(expression/unknown)"
                        )
                        unique = "unique" if index[2] else "non-unique"
                        origin = str(index[3]) if len(index) > 3 else "unknown"
                        lines.append(f"- {index_name} ({names}) [{unique}; origin={origin}]")
                else:
                    lines.append("- (none declared)")

            semantic_for_table = _semantic_context_from_text(
                _read_semantic_text(), [table]
            )
            samples, samples_are_relevant = _question_relevant_samples(
                conn,
                table,
                columns,
                question,
                semantic_for_table,
            )
            lines.append(
                "Question-relevant sample rows:"
                if samples_are_relevant
                else "Sample rows:"
            )
            if samples:
                for index, sample in enumerate(samples, start=1):
                    pairs = ", ".join(f"{key}={sample[key]}" for key in sample.keys())
                    lines.append(f"- sample {index}: {pairs}")
            else:
                lines.append("- (no rows)")
            lines.append("")

    semantic = _load_semantic_context(requested)
    if semantic:
        lines.extend(
            [
                "SEMANTIC LAYER (advisory; the live schema above is authoritative):",
                semantic,
            ]
        )
    return "\n".join(lines)


@tool
def get_semantic_context(table_names: str = "") -> str:
    """Return advisory business meaning from schema_summary.md.

    Optionally pass comma-separated table names to select relevant passages.
    The live schema tools remain authoritative for tables and columns.
    """

    # 요청한 테이블과 관련된 schema_summary 문서 및 설정된 업무 의미를 보조 자료로 제공한다.
    # 문서가 없으면 라이브 스키마를 사용하라는 안내를 반환한다.

    requested = [name.strip() for name in table_names.split(",") if name.strip()]
    semantic = _load_semantic_context(requested)
    if not semantic:
        return "No semantic metadata is available; use the live relational schema."
    configured = semantic_execution_context()
    return (
        "Semantic metadata is advisory; verify every table and column with get_table_schema.\n"
        + semantic
        + ("\n\n" + configured if configured else "")
    )


@tool
def discover_relationships(table_names: str, candidate_table_names: str = "") -> str:
    """Discover possible joins from identifier names and live value overlap.

    Pass comma-separated tables already known to be relevant. Candidates are
    inferred from the current database; no domain table or value is predefined.
    Optionally pass ``candidate_table_names`` to limit relationship targets to
    an already retrieved seed set; omit it when a missing bridge must be found.
    Verify candidate schemas before using them in SQL.
    """

    # 관련 테이블에서 외래 키·정규화한 ID 이름·실제 값 중첩을 이용해 연결 후보를 찾는다.
    # 대상 후보 목록이 있으면 그 범위에서, 없으면 전체 DB에서 탐색한다.
    # 실제 조인에 쓰기 전 각 테이블 스키마를 확인할 수 있도록 근거가 포함된 설명을 반환한다.

    requested = [name.strip() for name in table_names.split(",") if name.strip()]
    if not requested:
        return "No table names were provided."
    candidates: list[tuple[int, str]] = []
    with closing(create_read_only_connection(DEFAULT_DB_PATH)) as conn:
        all_tables = [
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
        column_cache = {
            table: conn.execute(f"PRAGMA table_info({_quote(table)})").fetchall()
            for table in all_tables
        }
        allowed_targets = {
            name.strip()
            for name in candidate_table_names.split(",")
            if name.strip()
        }
        target_tables = (
            [table for table in all_tables if table in allowed_targets]
            if allowed_targets
            else all_tables
        )
        for source_table in requested:
            if source_table not in column_cache:
                continue
            for foreign_key in conn.execute(
                f"PRAGMA foreign_key_list({_quote(source_table)})"
            ).fetchall():
                target_table = str(foreign_key[2])
                if allowed_targets and target_table not in allowed_targets:
                    continue
                source_name = str(foreign_key[3])
                target_name = str(foreign_key[4])
                candidates.append((
                    5,
                    f"- {source_table}.{source_name} -> {target_table}.{target_name} "
                    "[declared foreign key]",
                ))
            for source_column in column_cache[source_table]:
                source_name = str(source_column[1])
                if not _is_identifier_column(source_name):
                    continue
                normalized_source = _normalized_identifier(source_name)
                for target_table in target_tables:
                    if target_table == source_table:
                        continue
                    for target_column in column_cache[target_table]:
                        target_name = str(target_column[1])
                        if not _is_identifier_column(target_name):
                            continue
                        if normalized_source != _normalized_identifier(target_name):
                            continue
                        overlaps = _has_value_overlap(
                            conn,
                            source_table,
                            source_name,
                            target_table,
                            target_name,
                        )
                        exact_name = source_name.lower() == target_name.lower()
                        score = (2 if overlaps else 0) + (1 if exact_name else 0)
                        overlap_text = "yes" if overlaps else "not found in sampled join"
                        candidates.append(
                            (
                                score,
                                f"- {source_table}.{source_name} -> "
                                f"{target_table}.{target_name} "
                                f"[normalized identifier={normalized_source}; value overlap={overlap_text}]",
                            )
                        )
    if not candidates:
        return "No identifier-based relationship candidates were discovered."
    candidates = list({description: (score, description) for score, description in candidates}.values())
    candidates.sort(key=lambda item: (-item[0], item[1]))
    lines = [
        "Possible relationships (heuristic; inspect both schemas before joining):",
        *(description for _, description in candidates[:30]),
    ]
    return "\n".join(lines)


def _quote(identifier: str) -> str:
    """SQLite 식별자 내부의 큰따옴표를 이중 처리하고 전체를 큰따옴표로 감싼다.

    테이블·컬럼 이름을 SQL에 삽입할 때 사용하며 데이터 값용 바인딩을 대신하지 않는다.
    """

    return '"' + identifier.replace('"', '""') + '"'


def _discover_temporal_ranges(conn: sqlite3.Connection, tables: list[str]) -> list[str]:
    """이름·선언 타입이 날짜 계열인 컬럼의 최소·최대 값을 읽는다.

    최댓값 기준으로 정렬한 최대 20개 범위 설명을 반환하며 조회할 수 없는 컬럼은 건너뛴다.
    """

    candidates: list[tuple[str, str]] = []
    name_pattern = re.compile(r"(?:^|_)(?:date|time|timestamp|at)$", re.IGNORECASE)
    for table in tables:
        columns = conn.execute(f"PRAGMA table_info({_quote(table)})").fetchall()
        for column in columns:
            name = str(column[1])
            declared_type = str(column[2] or "")
            is_temporal = (
                name_pattern.search(name)
                or "DATE" in declared_type.upper()
                or "TIME" in declared_type.upper()
            )
            if not is_temporal:
                continue
            try:
                minimum, maximum = conn.execute(
                    f"SELECT MIN({_quote(name)}), MAX({_quote(name)}) FROM {_quote(table)} "
                    f"WHERE {_quote(name)} IS NOT NULL"
                ).fetchone()
            except sqlite3.Error:
                continue
            if maximum is not None:
                candidates.append((str(maximum), f"{table}.{name}: {minimum} .. {maximum}"))
    candidates.sort(key=lambda item: item[0], reverse=True)
    return [description for _, description in candidates[:20]]


def _append_data_profile(
    lines: list[str],
    conn: sqlite3.Connection,
    table: str,
    columns: list[sqlite3.Row],
) -> None:
    """행 수·식별자 고유값 수·날짜 범위·저빈도 범주값 분포를 스키마 설명 목록에 덧붙인다.

    조인 확장 중복과 필터 후보를 판단할 근거를 제공하며 전달된 lines 목록을 직접 수정한다.
    """

    try:
        row_count = int(conn.execute(f"SELECT COUNT(*) FROM {_quote(table)}").fetchone()[0])
    except (sqlite3.Error, TypeError, ValueError):
        row_count = -1
    lines.append("Data profile:")
    lines.append(f"- rows: {row_count}" if row_count >= 0 else "- rows: unavailable")

    identifier_columns = [
        str(column[1]) for column in columns if _is_identifier_column(str(column[1]))
    ]
    if identifier_columns:
        lines.append("- identifier cardinality:")
        for column in identifier_columns[:12]:
            try:
                distinct = conn.execute(
                    f"SELECT COUNT(DISTINCT {_quote(column)}) FROM {_quote(table)}"
                ).fetchone()[0]
            except sqlite3.Error:
                continue
            lines.append(f"  - {column}: {distinct} distinct")

    for column in columns:
        name = str(column[1])
        declared_type = str(column[2] or "")
        if _is_temporal_column(name, declared_type):
            try:
                minimum, maximum = conn.execute(
                    f"SELECT MIN({_quote(name)}), MAX({_quote(name)}) "
                    f"FROM {_quote(table)} WHERE {_quote(name)} IS NOT NULL"
                ).fetchone()
            except sqlite3.Error:
                continue
            if maximum is not None:
                lines.append(f"- temporal range {name}: {minimum} .. {maximum}")

    categorical: list[str] = []
    for column in columns:
        name = str(column[1])
        declared_type = str(column[2] or "")
        if _is_identifier_column(name) or _is_temporal_column(name, declared_type):
            continue
        try:
            values = conn.execute(
                f"SELECT {_quote(name)}, COUNT(*) AS frequency FROM {_quote(table)} "
                f"WHERE {_quote(name)} IS NOT NULL GROUP BY {_quote(name)} "
                "ORDER BY frequency DESC LIMIT 21"
            ).fetchall()
        except sqlite3.Error:
            continue
        if not values or len(values) > 20:
            continue
        rendered = ", ".join(
            f"{_short_value(value[0])} ({value[1]})" for value in values
        )
        categorical.append(f"  - {name}: {rendered}")
    if categorical:
        lines.append("- low-cardinality values:")
        lines.extend(categorical)


def _is_identifier_column(name: str) -> bool:
    """컬럼명이 id 또는 *_id인지 대소문자를 무시해 확인한다.

    식별자 통계와 관계 후보를 고를 때 사용하는 이름 기반 규칙이다.
    """

    normalized = name.lower()
    return normalized == "id" or normalized.endswith("_id")


def _normalized_identifier(name: str) -> str:
    """식별자 이름을 소문자로 바꾸고 반복된 ocel_ 접두사를 제거한다.

    서로 다른 테이블의 이름 변형을 같은 관계 후보로 비교하기 위한 정규화다.
    """

    normalized = name.lower()
    while normalized.startswith("ocel_"):
        normalized = normalized.removeprefix("ocel_")
    return normalized


def _is_temporal_column(name: str, declared_type: str) -> bool:
    """컬럼명의 날짜·시간 접미사와 선언 타입의 DATE/TIME 여부를 확인한다.

    시간 범위 조회 대상과 일반 범주값 검색 대상을 구분하는 데 사용한다.
    """

    name_pattern = re.compile(r"(?:^|_)(?:date|time|timestamp|at)$", re.IGNORECASE)
    return bool(
        name_pattern.search(name)
        or "DATE" in declared_type.upper()
        or "TIME" in declared_type.upper()
    )


def _has_value_overlap(
    conn: sqlite3.Connection,
    source_table: str,
    source_column: str,
    target_table: str,
    target_column: str,
) -> bool:
    """두 테이블의 지정 컬럼을 조인해 일치하는 비어 있지 않은 값이 하나라도 있는지 확인한다.

    첫 일치만 조회하며 SQLite 오류가 나면 False로 처리한다.
    """

    try:
        row = conn.execute(
            f"SELECT 1 FROM {_quote(source_table)} AS source "
            f"JOIN {_quote(target_table)} AS target "
            f"ON source.{_quote(source_column)} = target.{_quote(target_column)} "
            f"WHERE source.{_quote(source_column)} IS NOT NULL LIMIT 1"
        ).fetchone()
    except sqlite3.Error:
        return False
    return row is not None


def _short_value(value: object) -> str:
    """값을 한 줄 문자열로 만들고 최대 80자로 줄인다.

    샘플·검색 근거 설명이 지나치게 길어지는 것을 막는 표시용 처리다.
    """

    rendered = str(value).replace("\n", " ")
    return rendered if len(rendered) <= 80 else rendered[:77] + "..."


def _current_question(question: str) -> str:
    """직렬화된 이전 결과 블록을 제외하고 현재 사용자 질문 부분을 추출한다.

    질문 안내 접두사와 바깥 공백도 제거해 스키마 검색에 사용할 텍스트를 반환한다.
    """

    lowered = question.lower()
    marker = "previous results from this thread"
    marker_index = lowered.find(marker)
    current = question[:marker_index] if marker_index >= 0 else question
    return current.removeprefix("Current user question:").strip()


def _looks_like_followup(question: str) -> bool:
    """질문에 이전 결과 안내나 그·이전·해당 등의 후속 참조 표지가 있는지 확인한다.

    의미를 확정하는 분류기가 아니라 이전 테이블 검색 우대에 사용하는 휴리스틱이다.
    """

    lowered = question.lower()
    return any(marker in lowered for marker in _FOLLOWUP_MARKERS)


def _tokens(text: str) -> set[str]:
    """영문·숫자·한국어 토큰을 추출해 소문자 집합으로 만든다.

    언더스코어는 공백처럼 처리하고 너무 짧은 토큰은 제외한다.
    """

    return {
        match.group(0).lower()
        for match in _TOKEN_PATTERN.finditer(text.replace("_", " "))
        if len(match.group(0)) >= 2
    }


def _schema_match_score(
    question: str,
    table_name: str,
    document: str,
) -> tuple[float, float, set[str]]:
    """질문의 단어와 테이블·검색 문서의 정확·부분·유사 일치 점수를 계산한다.

    어휘 점수·문자열 유사도 점수·일치 근거 집합을 반환해 후보 순위를 구성한다.
    """

    question_lower = question.lower()
    document_lower = document.lower()
    question_tokens = _tokens(question)
    document_tokens = _tokens(document)
    matched: set[str] = set()
    lexical_score = 0.0
    fuzzy_score = 0.0

    if table_name.lower() in question_lower:
        lexical_score += 12.0
        matched.add(table_name)
    for term in question_tokens:
        if term in document_tokens:
            lexical_score += 4.0
            matched.add(term)
            continue
        if len(term) >= 2 and any(
            term in token or token in term
            for token in document_tokens
            if len(token) >= 2
        ):
            lexical_score += 1.25
            matched.add(term)
        if len(term) >= 3 and term in document_lower:
            lexical_score += 0.75
        best_similarity = max(
            (_token_similarity(term, token) for token in document_tokens),
            default=0.0,
        )
        if best_similarity >= 0.72 and term not in document_tokens:
            fuzzy_score += best_similarity * 1.5
            matched.add(f"~{term}")
    return lexical_score, fuzzy_score, matched


def _retrieval_features(
    conn: sqlite3.Connection,
    table: str,
    semantic_text: str,
) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    """테이블 이름·컬럼·관련 의미 문서·제한된 고유값에서 검색용 문서를 만든다.

    날짜 컬럼은 값 검색에서 제외하고 값 종류가 적은 컬럼의 값만 문서에 보충한다.
    문서 문자열과 컬럼·값 튜플을 함께 반환한다.
    """

    columns = conn.execute(f"PRAGMA table_info({_quote(table)})").fetchall()
    parts = [table, " ".join(str(column[1]) for column in columns)]
    semantic = _semantic_context_from_text(semantic_text, [table])
    if semantic:
        parts.append(semantic)

    values: list[str] = []
    for column in columns:
        name = str(column[1])
        declared_type = str(column[2] or "")
        if _is_temporal_column(name, declared_type):
            continue
        limit = 51 if _is_identifier_column(name) else 13
        try:
            rows = conn.execute(
                f"SELECT DISTINCT {_quote(name)} FROM {_quote(table)} "
                f"WHERE {_quote(name)} IS NOT NULL LIMIT {limit}"
            ).fetchall()
        except sqlite3.Error:
            continue
        maximum = 50 if _is_identifier_column(name) else 12
        if 0 < len(rows) <= maximum:
            values.extend(str(row[0]) for row in rows)
    if values:
        parts.append(" ".join(values))
    return (
        "\n".join(parts),
        tuple(str(column[1]) for column in columns),
        tuple(dict.fromkeys(values)),
    )


def _matched_schema_items(
    question: str,
    items: Iterable[str],
    *,
    value_mode: bool = False,
) -> list[str]:
    """질문과 정확 또는 유사하게 일치하는 컬럼명·표본 값을 찾는다.

    값 검색에는 더 엄격한 임계값과 더 작은 개수 제한을 적용하고 표시 문자열 목록을 반환한다.
    """

    lowered = question.casefold()
    question_tokens = _tokens(question)
    matched: list[str] = []
    for item in items:
        rendered = str(item).strip()
        if not rendered:
            continue
        item_lower = rendered.casefold()
        item_tokens = _tokens(rendered)
        exact = item_lower in lowered or bool(question_tokens & item_tokens)
        fuzzy = any(
            _token_similarity(question_token, item_token) >= (0.86 if value_mode else 0.74)
            for question_token in question_tokens
            for item_token in item_tokens
        )
        if exact or fuzzy:
            matched.append(_short_value(rendered))
        if len(matched) >= (4 if value_mode else 8):
            break
    return matched


def _token_similarity(left: str, right: str) -> float:
    """두 문자열의 순서 유사도와 문자 n-gram 집합의 Jaccard 유사도를 계산한다.

    두 점수 중 큰 값을 반환하며 입력이 비어 있으면 0으로 처리한다.
    """

    if not left or not right:
        return 0.0
    sequence = SequenceMatcher(None, left.casefold(), right.casefold()).ratio()
    left_grams = _character_ngrams(left.casefold())
    right_grams = _character_ngrams(right.casefold())
    union = left_grams | right_grams
    jaccard = len(left_grams & right_grams) / len(union) if union else 0.0
    return max(sequence, jaccard)


def _character_ngrams(value: str, size: int = 3) -> set[str]:
    """공백을 제거한 문자열을 길이 size의 겹치는 조각 집합으로 나눈다.

    짧은 문자열은 전체를 한 조각으로 만들어 유사도 계산에 사용한다.
    """

    compact = re.sub(r"\s+", "", value)
    if len(compact) <= size:
        return {compact}
    return {compact[index:index + size] for index in range(len(compact) - size + 1)}


def _schema_join_graph(
    conn: sqlite3.Connection,
    tables: list[str],
) -> dict[str, set[str]]:
    """테이블을 정점으로 하고 외래 키·공통 정규화 ID·설정된 관계를 연결한 무방향 그래프를 만든다.

    현재 구현은 이 단계에서 실제 값 중첩을 검증하지 않으며 연결 테이블 탐색의 후보 그래프다.
    """

    graph = {table: set() for table in tables}
    identifiers: dict[str, set[str]] = {}
    for table in tables:
        columns = conn.execute(f"PRAGMA table_info({_quote(table)})").fetchall()
        identifiers[table] = {
            _normalized_identifier(str(column[1]))
            for column in columns
            if _is_identifier_column(str(column[1]))
        }
        for foreign_key in conn.execute(f"PRAGMA foreign_key_list({_quote(table)})").fetchall():
            target = str(foreign_key[2])
            if target in graph:
                graph[table].add(target)
                graph[target].add(table)
    for index, left in enumerate(tables):
        for right in tables[index + 1:]:
            if identifiers[left] & identifiers[right]:
                graph[left].add(right)
                graph[right].add(left)
    from app.execution.analysis_semantics import load_analysis_semantics

    for scope in load_analysis_semantics().get("relationship_scopes", []):
        if not isinstance(scope, dict):
            continue
        left = str(scope.get("event_object_table") or "")
        right = str(scope.get("membership_table") or "")
        if left in graph and right in graph:
            graph[left].add(right)
            graph[right].add(left)
    return graph


def _shortest_path(
    graph: dict[str, set[str]],
    source: str,
    target: str,
) -> list[str]:
    """테이블 연결 그래프에서 너비 우선 탐색으로 두 테이블 사이 최단 경로를 찾는다.

    연결돼 있지 않으면 빈 목록을 반환해 불필요한 연결 테이블 추가를 피한다.
    """

    if source == target:
        return [source]
    queue: list[list[str]] = [[source]]
    visited = {source}
    while queue:
        path = queue.pop(0)
        for neighbor in sorted(graph.get(path[-1], set())):
            if neighbor in visited:
                continue
            candidate = [*path, neighbor]
            if neighbor == target:
                return candidate
            visited.add(neighbor)
            queue.append(candidate)
    return []


def _question_relevant_samples(
    conn: sqlite3.Connection,
    table: str,
    columns: list[sqlite3.Row],
    question: str,
    semantic_context: str,
) -> tuple[list[sqlite3.Row], bool]:
    """질문 단어와 관련 의미 문서의 값으로 제한된 표본 행을 우선 조회한다.

    중복을 제거한 최대 3개 행과 질문 관련 표본 여부를 반환한다.
    일치 표본이 없으면 일반 표본으로 대체하고 조회 실패는 빈 목록으로 처리한다.
    """

    text_columns = [
        str(column[1])
        for column in columns
        if not _is_temporal_column(str(column[1]), str(column[2] or ""))
    ][:16]
    current = _current_question(question)
    question_terms = [term for term in _tokens(current) if len(term) >= 3]
    semantic_literals: list[str] = []
    for paragraph in re.split(r"\n\s*\n", semantic_context):
        paragraph_tokens = _tokens(paragraph)
        if question_terms and not any(
            term in paragraph_tokens
            or any(term in token or token in term for token in paragraph_tokens)
            for term in question_terms
        ):
            continue
        semantic_literals.extend(re.findall(r"'([^']{1,120})'", paragraph))

    predicates: list[tuple[str, str]] = []
    for literal in dict.fromkeys(semantic_literals):
        for column in text_columns:
            predicates.append((f"CAST({_quote(column)} AS TEXT) = ?", literal))
    for term in question_terms:
        if term.isdigit():
            continue
        for column in text_columns:
            predicates.append((f"LOWER(CAST({_quote(column)} AS TEXT)) LIKE ?", f"%{term.lower()}%"))

    samples: list[sqlite3.Row] = []
    seen: set[tuple[object, ...]] = set()
    for predicate, value in predicates[:80]:
        try:
            rows = conn.execute(
                f"SELECT * FROM {_quote(table)} WHERE {predicate} LIMIT 3",
                (value,),
            ).fetchall()
        except sqlite3.Error:
            continue
        for row in rows:
            key = tuple(row)
            if key in seen:
                continue
            seen.add(key)
            samples.append(row)
            if len(samples) >= 3:
                return samples, True
    if samples:
        return samples, True
    try:
        return conn.execute(f"SELECT * FROM {_quote(table)} LIMIT 3").fetchall(), False
    except sqlite3.Error:
        return [], False


def _schema_summary_path() -> Path:
    """SCHEMA_SUMMARY_PATH가 지정되면 그 경로를, 아니면 기본 의미 문서 경로를 선택한다.

    설정 경로의 홈 축약을 확장해 반환한다.
    """

    configured = os.environ.get("SCHEMA_SUMMARY_PATH")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[2] / "Data" / "docs" / "schema_summary.md"


def _read_semantic_text() -> str:
    """선택된 스키마 의미 문서를 UTF-8로 읽는다.

    파일을 읽을 수 없으면 빈 문자열을 반환해 라이브 스키마 탐색을 계속할 수 있게 한다.
    """

    path = _schema_summary_path()
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _semantic_context_from_text(text: str, table_names: list[str]) -> str:
    """의미 문서에서 요청 테이블과 관련된 Markdown 구역 또는 문단만 골라 연결한다.

    테이블 목록이 없으면 전체 문서를 대상으로 하고 환경 변수의 최대 길이로 제한한다.
    """

    if not text:
        return ""

    max_chars = int(os.environ.get("SCHEMA_SEMANTIC_MAX_CHARS", "12000"))
    if not table_names:
        return text[:max_chars]

    markdown_sections = [
        section.strip()
        for section in re.split(r"(?=^#{1,6}\s+)", text, flags=re.MULTILINE)
        if section.strip()
    ]
    paragraphs = markdown_sections or re.split(r"\n\s*\n", text)
    selected: list[str] = []
    for paragraph in paragraphs:
        heading = paragraph.splitlines()[0].lstrip("# ").strip().lower()
        if markdown_sections:
            matches = any(
                heading == table.lower()
                or re.search(rf"`{re.escape(table)}`", paragraph, re.IGNORECASE)
                for table in table_names
            )
        else:
            matches = any(
                re.search(rf"(?<![\w]){re.escape(table)}(?![\w])", paragraph)
                for table in table_names
            )
        if matches:
            selected.append(paragraph.strip())
    return "\n\n".join(selected)[:max_chars]


def _load_semantic_context(table_names: list[str]) -> str:
    """의미 문서를 읽고 요청 테이블에 해당하는 부분을 추출한다.

    문서 접근과 구역 선택을 결합한 공통 보조 함수다.
    """

    return _semantic_context_from_text(_read_semantic_text(), table_names)
