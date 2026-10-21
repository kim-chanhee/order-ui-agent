"""HTTP 입구.

요청/응답 스키마(`schemas`), 공통 오류(`errors`), 웹 셸(`web_ui`)과
공통 채팅(`chat`)·실험 관리(`experiment`)와 A2UI 전용 계획 검토(`a2ui.review`) 라우터를 둔다.
`api`가 기능별 라우터를 모으고, `server.py`가 이를 앱에 붙인다.
"""
