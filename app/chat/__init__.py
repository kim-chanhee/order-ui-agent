"""두 모드가 공유하는 대화 분류와 문맥 관리 계층.

service.py는 요청 진입점, dispatch.py는 모드·요청별 분기를 담당한다.
turn_router.py는 LLM 분류와 실행 조건 검증, responses.py는 답변 생성을 담당한다.
thread_context.py는 분석 근거와 모드별 최근 문답을 관리하며, summary.py는 요약 진입점이다.
검증 오류는 LLM에 전달해 한 번 재판단하고, 복구되지 않으면 확인 질문을 생성한다.
모든 LLM 응답 시도가 실패한 경우에만 공통 장애 문구를 사용한다.
A2UI 전용 계획 검토 응답은 a2ui/review.py에 둔다.
"""
