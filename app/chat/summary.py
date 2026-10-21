"""저장된 분석 결과를 공통 LLM 응답 계층으로 요약하는 호환 진입점.

결과 요약은 turn_router의 근거 제한과 공통 장애 처리를 함께 사용한다.
이전 답변을 단순 나열하는 대체 요약 대신 LLM이 현재 요청에 맞게 작성한다.
호출자가 사용하는 'Answer:' 접두사 형식은 유지한다.
"""

from app.chat.turn_router import respond_from_results


def summarize_records(question: str, records: list[dict]) -> str:
    """저장된 결과를 LLM으로 요약하고 기존 호출 형식의 Answer: 접두사를 보장한다."""

    answer = respond_from_results(question, records, "summarize_results")
    return answer if answer.startswith("Answer:") else f"Answer: {answer}"
