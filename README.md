# Agent2UI · 실행 전 분석 계획을 검토하는 데이터 분석 UI

[![CI](https://github.com/kim-chanhee/order-ui-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/kim-chanhee/order-ui-agent/actions/workflows/ci.yml)

**자연어 질문 → 분석 계획 UI → 사용자 수정·확정 → SQL 검증·실행 → 결과**

SQL을 모르는 사용자가 AI의 해석을 확인하고 수정할 수 있도록 만든 연구용 웹 시스템입니다. 물류·주문 데이터 분석을 대상으로, 질문을 즉시 실행하는 프롬프트 방식과 실행 전에 분석 계획을 검토하는 Agent2UI 방식을 비교합니다.

[빠른 시작](#빠른-시작) · [사용 화면](docs/system-guide.md#사용-화면) · [구조와 설계](#시스템-구조) · [설치·문제 해결](docs/getting-started.md) · [API](app/routes/README.md)

## 어떤 문제를 해결하나요?

“최근 60일 배송 실패 주문 건수”라는 질문도 기준일, 실패 조건, 주문 중복 처리에 따라 답이 달라집니다. 결과만 보면 사용자가 AI의 해석을 확인하기 어렵습니다.

Agent2UI는 기간·필터·지표·집계 기준을 편집 가능한 UI로 먼저 보여줍니다. 사용자가 계획을 확정하면, 그 계획과 생성 SQL의 일치 여부를 검사한 뒤 조회합니다.

| 단계 | 프롬프트 모드(Baseline) | Agent2UI 모드 |
|---|---|---|
| 질문 | 자연어 입력 | 자연어 입력 |
| 분석 계획 | 내부 생성 | 내부 생성 후 편집 UI로 표시 |
| 수정 | 후속 질문 | 입력 요소 수정·자연어 조건 추가 |
| 실행 | 검토 단계 없이 실행 | 사용자 확정 후 실행 |
| 결과 | 설명·표·차트 | 설명·표·차트 |

**두 모드는 같은 계획 생성기·SQL 실행 계층·결과 렌더러를 공유합니다.** 이 프로젝트의 핵심 설계는 실행 전 계획 검토, 사용자 수정 내용의 실행 반영, 계획과 SQL의 일치 검증입니다.

![조회 기간·결과 방식·집계 기준을 검토하는 Agent2UI 화면](docs/images/agent2ui-plan.png)

기존 주문 DB를 사용한 계획 화면 일부입니다. [질문·결과·후속 질문 화면 전체 보기](docs/system-guide.md#사용-화면)

## 빠른 시작

Python **3.13+**, [uv](https://docs.astral.sh/uv/getting-started/installation/), 모델 API 키가 필요합니다. 아래 예제는 실제 주문·참가자 자료 대신 합성 데이터를 사용합니다.

```bash
git clone https://github.com/kim-chanhee/order-ui-agent.git
cd order-ui-agent
uv sync --dev --locked
python3 scripts/create_demo_db.py
cp -n examples/demo/.env.example .env
# .env의 OPENAI_API_KEY와 모델 설정을 입력하세요.
uv run order-ui-agent
```

<http://127.0.0.1:8000> → **관리자 모드** → 프롬프트 또는 Agent2UI 선택. 기존 `.env`가 있다면 데모용 경로를 수동 반영하세요. 데모 생성기는 기존 DB를 덮어쓰지 않습니다.

| 데모 질문 | 합성 데이터 정답 |
|---|---|
| 전체 주문은 몇 건이야? | 8건 |
| 배송 실패 주문은 몇 건이야? | 3건 |
| 배송 실패 주문을 상품별로 집계해줘 | Alpha 2건, Beta 1건 |

Agent2UI에서는 생성된 계획의 필터·집계 기준을 확인하고 확정합니다. 정답은 데이터 기준이며 실제 LLM 응답의 정확도는 별도 확인이 필요합니다. 기존 화면 캡처의 데이터·숫자는 합성 데모와 다릅니다.

[설치·환경 설정·직접 SQL 확인·오류 해결](docs/getting-started.md)

## 시스템 구조

![자연어 입력에서 두 모드의 처리와 SQL 검증·실행 및 결과까지의 시스템 구조도](docs/images/system-architecture.png)

발표 구조도의 Baseline “직접 SQL 생성”은 사용자 검토 단계를 생략한 흐름입니다. 현재 코드에서는 Baseline도 내부 계획을 생성합니다.

| 설계 | 구현 방식과 이유 | 코드 |
|---|---|---|
| 구조화된 분석 계획 | 질문을 기간·필터·지표·집계 기준으로 표현해 UI와 실행의 공통 기준으로 사용 | [planning](app/planning/analysis_models.py) |
| 계획과 SQL 일치 검사 | 사용자가 확정한 조건이 실행 쿼리에 반영됐는지 AST 기반 검사 | [SQL 계약](app/execution/sql_contract.py) |
| 읽기 전용 조회 | SQL 검사와 SQLite authorizer·읽기 전용 연결로 데이터 변경 차단 | [SQL 안전성](app/execution/sql_safety.py) |
| 계획 화면 버전 관리 | 이전 화면의 확정 요청을 거절해 수정 내용과 실행 상태의 충돌 방지 | [검토 API](app/routes/a2ui/review.py) |
| 공통 실행·결과 계층 | 두 방식의 차이를 사용자 검토 단계에 두고 실행·표시 체계 공유 | [백엔드 구조](app/README.md) |

**기술:** Python · FastAPI · Pydantic · LangChain OpenAI 연동 · SQLGlot · SQLite · JavaScript ES Modules

`app/planning`은 계획 생성, `app/execution`은 SQL 검증·실행, `app/a2ui`와 `app/static`은 화면 정의와 렌더링, `app/runtime`은 대화·실행 상태를 담당합니다. 여기서 Agent2UI는 본 프로젝트의 인터랙션 방식 이름이며, 화면 전송 모델과 렌더러는 저장소 내부에 구현되어 있습니다. 외부 A2UI 표준과의 완전한 호환성을 검증한 프로젝트는 아닙니다.

[분석 계획 JSON → UI 생성 예시와 상세 구조](docs/system-guide.md#분석-계획에서-확인-ui로)

## 검증 범위와 현재 한계

```bash
uv run pytest tests/execution -q
```

- 임시 SQLite와 대체 LLM 응답으로 쓰기·다중 문장 차단, 검사 순서, 계획과 SQL 불일치, 기간 처리, 모드별 실행 경로를 검증합니다. CI에서 같은 테스트를 실행합니다.
- 실제 모델의 자연어 해석 정확도, 응답 시간, 브라우저 전체 동작은 이 테스트만으로 보장하지 않습니다.
- 현재 조회 대상은 SQLite입니다. 다른 도메인에서는 스키마 설명·별칭·의미 규칙을 조정해야 합니다.
- 연구·로컬 시연용 시스템입니다. 관리자 화면은 운영 환경의 인증·권한 관리 체계를 대신하지 않습니다.
- 원본 주문 DB, 참가자 목록, 설문·로그 원자료는 공개하지 않습니다. 비교 실험 코드는 포함하지만, 이 저장소만으로 원래 사용자 연구를 재현할 수는 없습니다.

연구 평가는 시스템 구현과 구분해 [평가 절차](docs/system-guide.md#연구-평가-절차)에 설명합니다. 구현 여부와 사용자 경험 개선에 대한 통계적 증거는 별도로 판단해야 합니다.

## 문서 안내

| 목적 | 문서 |
|---|---|
| 설치·합성 데모·본인 DB 연결·문제 해결 | [시작 안내](docs/getting-started.md) |
| 모든 화면·구조도·계획 UI 생성·평가 절차 | [시스템 상세 설명](docs/system-guide.md) |
| 공통·모드별 코드와 요청 경로 | [백엔드](app/README.md) · [API](app/routes/README.md) |
| 화면 상태와 컴포넌트 구성 | [프론트엔드](app/static/README.md) |
| 테스트가 확인하는 조건 | [실행 검증](tests/execution/README.md) |

## 앞으로 보완할 부분

- 브라우저에서 질문 → 계획 수정 → 실행까지의 짧은 시연 영상
- 실제 모델 기반 평가셋·측정 조건·실패 예시 공개
- 프론트엔드 및 전체 사용자 흐름 자동 검증

위 항목은 향후 작업이며 현재 구현·검증된 기능과 구분합니다.
