# `app/static/a2ui` · 계획 검토 화면 스타일

Agent2UI 계획 카드, 편집 입력, 확정 상태와 후속 동작에 쓰는 CSS를 관리합니다.

## 주요 파일

| 파일 | 역할 |
|---|---|
| [review.css](review.css) | 계획 카드·편집 입력·확정 상태·후속 동작 스타일. |

## 연결 흐름

templates/index.html이 공통 static/styles.css 다음에 review.css를 로드합니다. 화면 구성·이벤트 처리는 static/js/a2ui의 JavaScript가 담당합니다.

## 함께 읽기

- [상위 폴더 안내](../README.md)
- [앱 전체 구조](../../README.md)
- [프로젝트 소개](../../../README.md)
