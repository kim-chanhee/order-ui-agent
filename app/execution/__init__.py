"""분석 계획을 실제 DB 조회와 결과 응답으로 연결하는 실행 계층.

baseline/과 a2ui/ 서비스가 confirmed_context와 confirmed_execution을 공유한다.
agent/는 LLM 추론과 도구 호출, tools/는 스키마 탐색과 검사·실행 도구,
sql/은 SQL 파싱·계약·안전성·DB 실행, semantics/는 업무·집계·기간 규칙,
results/는 결과 계약과 실패 응답 데이터를 담당한다.
"""
