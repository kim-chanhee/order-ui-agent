# `app/static/js/a2ui/plan` · 분석 계획 편집 UI

분석 계획을 정규화하고 입력 블록·안내 문장·변경 차이·필수값 검사를 구성합니다.

## 주요 파일

| 파일 | 역할 |
|---|---|
| [condition-evaluator.js](condition-evaluator.js) | UI 블록의 표시·필수 입력 조건 평가. |
| [plan-diff.js](plan-diff.js) | 최초 계획과 수정 계획의 변경 값·필드 계산. |
| [plan-labels.js](plan-labels.js) | 단위·지표·기간·집계 기준의 한글 표시 이름과 조사 처리. |
| [plan-normalizer.js](plan-normalizer.js) | 계획·UI 블록·집계 기준·필드 간 의존성 정규화. |
| [plan-renderer.js](plan-renderer.js) | 계획 카드·입력 블록 렌더링과 수정·확정 요청 데이터 구성. |
| [plan-sentence.js](plan-sentence.js) | 현재 계획의 분석 의미를 사용자 안내 문장으로 표현. |
| [plan-validation.js](plan-validation.js) | 확정 전 필수값·미해결 조건·계획 유효성 검사. |

## 연결 흐름

plan-renderer.js가 카드와 요청 payload를 만듭니다. 표시·필수 조건은 condition-evaluator.js, 확정 전 검사는 plan-validation.js, 수정 기록은 plan-diff.js가 담당합니다. 최종 실행 허용 여부는 서버에서도 검증합니다.

## 함께 읽기

- [상위 폴더 안내](../README.md)
- [앱 전체 구조](../../../../README.md)
- [프로젝트 소개](../../../../../README.md)

## 카드 검토 화면

결과 지표(다중 지표 포함), 집계 기준, 분석 기간, 대상 이벤트를 네 카드로 묶습니다.
선택한 카드의 서버 발급 입력만 펼치고 나머지 입력은 세부 조건에서 제공합니다.
`변경 저장`은 서버 검증과 revision 갱신을 수행하며, 실행 버튼도 미저장 변경을 먼저 저장합니다.
최초 추천 스냅샷과 마지막 저장 스냅샷을 분리해 변경 표시와 초기화를 유지합니다.
자연어 수정은 공통 채팅창에서 기존 refine API로 전달하고, 새 추천 이후에는 그 계획을 초기화 기준으로 삼습니다.
