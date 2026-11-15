# `app/templates` · 웹 앱 HTML 셸

> **한눈에 보기** · 브라우저가 처음 받는 기본 HTML 화면입니다. 이후 계획과 결과는 JavaScript가 데이터에 맞춰 추가합니다.

**기본 흐름:** 기본 HTML 제공 → JavaScript 시작 → 동적 화면 표시

모드 선택·프로필 입력·채팅 영역의 기본 HTML과 정적 리소스 로딩을 정의합니다.

## 주요 파일

| 파일 | 역할 |
|---|---|
| [index.html](index.html) | 모드 선택·사용자 프로필·채팅 영역과 CSS·JS 모듈 로딩. |

## 핵심 개념과 동작

HTML은 서버가 한 번 읽어 제공하는 앱 셸입니다. JavaScript가 데이터에 따라 계획과 결과 DOM을 추가하며 서버 템플릿에서 모델 출력을 마크업으로 직접 삽입하지 않습니다. 메타 viewport와 한국어 문서 언어를 선언합니다.

### 주요 함수·클래스

| 함수·클래스 | 구체적인 역할 | 관련 기술 |
|---|---|---|
| `load_index_html` | UTF-8 앱 셸 읽기 | 정적 셸 제공 |
| `INDEX_HTML` | 모듈 로딩 시 보존한 기본 HTML | 초기화 캐시 |

### 핵심 코드: <!doctype html>

브라우저 문서와 정적 스타일 로딩의 기준을 제공합니다.

**동작:** 문서 언어·인코딩·viewport를 선언하고 공통 스타일 뒤 전용 스타일을 로드합니다.

**설계:** HTML5 셸과 CSS cascade입니다. 런타임 화면 데이터와 기본 페이지 구조를 분리합니다.

**예:** GET /는 이 셸을 반환하고 채팅 응답은 이후 API로 받아 렌더링합니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [app/templates/index.html](index.html#L1). 아래는 실제 코드의 1~12행 발췌이며 앞뒤는 생략했습니다.

```html
<!doctype html>
<html lang="ko">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Schema-driven SQLite Agent</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700;1,9..40,400&family=Noto+Sans+KR:wght@400;500;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/static/styles.css?v=result-visibility-v2">
  <link rel="stylesheet" href="/static/a2ui/review.css?v=dynamic-blueprint-v1">
  </head>
```

</details>

### 다른 기능과 연결되는 순서

routes.web_ui가 파일을 읽고 routes.api.index가 HTML을 반환하며 server.py가 /static을 마운트합니다. 실제 채팅 이벤트는 모듈 스크립트 app.js가 연결합니다.

### 확인한 범위와 한계

외부 Google Fonts 사용은 네트워크 환경에 의존합니다. HTML 변경의 DOM ID와 JS 이벤트 바인딩 일치는 별도 확인이 필요하며 자동 브라우저 부팅 테스트는 현재 없습니다.

## 함께 읽기

- [앱 전체 구조](../README.md)
- [프로젝트 소개](../../README.md)
