"""분석 계획을 실제 DB 조회와 결과 응답으로 연결하는 실행 계층.

처리 흐름:
    baseline/service 또는 a2ui/service → confirmed_context → confirmed_execution
    → fast_sql_agent → 스키마 탐색·SQL 검증·실행 → 결과 검증·응답 조립.

파일별 책임:
    schema_tools: 실제 테이블·컬럼·관계 탐색.
    sql_tools: LLM이 호출하는 검사·실행 도구와 실행 상태.
    sql_safety: 읽기 전용 경계, sql_contract: 계획과 SQL의 일치 검사.
    temporal_policy/analysis_semantics: 기간·업무 규칙 검사.
    sql_builder: DB 실행과 표 표시, result_contract: 반환 결과 의미 검사.
    semantic_aliases/result_payload: 별칭·실패 데이터 처리.

Baseline은 계획을 만든 뒤 즉시 실행하고, A2UI는 사용자가 확인한 계획을 실행한다.
두 모드는 공통 SQL 에이전트와 검증·실행 경로를 공유한다.
"""
