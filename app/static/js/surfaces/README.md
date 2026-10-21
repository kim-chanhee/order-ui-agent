# `app/static/js/surfaces` · 서버 화면 정의의 검증과 렌더링

서버의 Surface 데이터를 검사하고 계획 또는 결과 화면의 렌더러로 연결합니다.

## 주요 파일

| 파일 | 역할 |
|---|---|
| [runtime.js](runtime.js) | 검증된 화면을 계획·결과 렌더러로 분기. |
| [validation.js](validation.js) | 화면 식별자·종류·컴포넌트 형식 검증. |

## 연결 흐름

runtime.js의 renderSurface가 validation.js를 거쳐 surface_type을 확인합니다. plan은 a2ui/surfaces.js, result는 공통 컴포넌트와 results 렌더러로 전달합니다.

## 함께 읽기

- [상위 폴더 안내](../README.md)
- [앱 전체 구조](../../../README.md)
- [프로젝트 소개](../../../../README.md)
