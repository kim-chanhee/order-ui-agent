# `app/routes/a2ui` · 계획 수정·확정 HTTP API

브라우저가 보내는 Agent2UI 계획 수정·확정 요청을 받고 서버가 발급한 화면 ID·버전을 확인합니다.

## 주요 파일

| 파일 | 역할 |
|---|---|
| [review.py](review.py) | A2UI 전용 분석 계획 확정·수정과 서버 발급 화면 검증 HTTP 라우터. |
| [schemas.py](schemas.py) | A2UI 전용 계획 확정·수정 요청과 응답 모델. |

## 연결 흐름

POST /api/review/refine은 계획 수정 후 revision을 올립니다. POST /api/review/confirm은 검증된 확정 계획을 실행 계층으로 전달합니다. 서버가 저장한 화면과 허용된 편집 범위를 검증합니다.

## 함께 읽기

- [상위 폴더 안내](../README.md)
- [앱 전체 구조](../../README.md)
- [프로젝트 소개](../../../README.md)

## 카드 편집 저장

`POST /api/review/update`는 현재 화면의 `plan`, `surface_id`, `plan_id`, `revision`, `question`을 받습니다.
서버에 저장된 입력 스키마로 편집 권한과 선택값을 검사하고, 이전 revision이 여전히 최신일 때만 원자적으로 새 revision을 저장합니다.
필수값이 덜 채워진 초안도 저장할 수 있지만 실행은 `/confirm`의 전체 검증을 통과해야 합니다. 저장 요청으로 SQL을 실행하지 않습니다.
`/refine`도 저장 시 버전 충돌을 검사합니다.
