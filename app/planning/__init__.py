"""Baseline과 A2UI가 공유하는 분석 계획 생성 계층.

파일별 역할:
    service.py         - 질문과 이전 분석 후보를 연결해 확인용 계획 생성
    planner/           - LLM 계획 생성과 응답 보정·UI 구성·후속 조건 상속
        dynamic_planner.py - 호출·후처리 순서·재시도·대체 계획
        models.py      - 계획 생성 응답과 후속 분석 맥락 모델
        prompt.py      - 질문·스키마·이전 분석을 결합한 프롬프트
        response.py    - 응답 구조·타입·필드와 원시 UI 값 복구
        controls.py    - 검토 UI 선택지 보충·중복 제거·배치
        context.py     - 후속 분석 참조 선택·조건 상속·ID 필터 근거 확인
        semantics.py   - 지표·관계 범위 정리와 의미·날짜 안내 검증
    analysis_models.py - SQL과 분리된 의미 기반 분석 계획 모델
    ui_models.py       - 두 모드가 공유하는 UI 블록과 계획 응답 모델
    schema_context.py  - 질문 관련 실제 스키마·관계·별칭 수집
    option_catalog.py  - 스키마와 현재 선택값에 근거한 편집 선택지 구성
    validator.py       - UI 조건 평가와 필수 입력 누락 계산
    a2ui/              - 검토 화면 응답, 추가 조건 수정, 확정·편집 범위 검증

처리 흐름:
    질문 → service → planner → 분석 계획과 UI 블록
    A2UI 사용자 확인 → a2ui/validator → 실행 계층
"""
