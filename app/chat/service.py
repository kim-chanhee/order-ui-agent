"""채팅 요청을 공통 대화 처리기로 전달하는 진입점.

요청에 thread ID가 없으면 새 UUID를 생성해 대화 식별자로 사용한다.
Baseline과 Agent2UI 모두 dispatch의 공통 요청 분류 경로로 전달하며,
Agent2UI의 분석 요청은 실행 전 확인 화면을 거친다.
일반 대화와 확인 질문도 최근 문답으로 저장해 다음 요청의 맥락으로 사용한다.
"""

from uuid import uuid4

from app.chat.dispatch import routed_chat_response
from app.chat.thread_context import remember_dialogue
from app.routes.schemas import ChatRequest


def chat_response_payload(payload: ChatRequest) -> dict:
    """기존 또는 새 thread ID로 요청을 전달하고 채팅 응답 딕셔너리를 반환한다."""
    response = routed_chat_response(payload, payload.thread_id or str(uuid4()))
    remember_dialogue(payload.question, response)
    return response
