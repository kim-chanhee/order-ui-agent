# 설치와 데모 실행

## 준비

Python 3.13 이상, [uv](https://docs.astral.sh/uv/getting-started/installation/), 사용할 모델에 접근 가능한 API 키가 필요합니다. 모델 요청에는 비용이 발생할 수 있습니다. 아래 명령은 프로젝트 루트에서 실행합니다.

```bash
git clone https://github.com/kim-chanhee/order-ui-agent.git
cd order-ui-agent
uv sync --dev --locked
python3 scripts/create_demo_db.py
```

데모 생성기는 실제 자료를 읽지 않고 코드에 정의된 가상 주문 8개로 `Data/demo.sqlite`를 만듭니다. 파일이 이미 있으면 덮어쓰지 않고 종료합니다. 이미 생성한 DB는 그대로 재사용하면 됩니다.

기존 `.env`가 없는 새 체크아웃에서 데모 설정을 복사합니다. 기존 설정이 있다면 보관하고 데모 예제의 경로 설정을 수동으로 반영하세요.

```bash
cp -n examples/demo/.env.example .env
```

`.env`의 `OPENAI_API_KEY=replace-me`를 본인 키로 바꿉니다. 예제 모델 이름은 설정값이며, 실제 사용 권한에 맞게 `AGENT_MODEL`과 `AGENT2UI_PLANNER_MODEL`을 변경할 수 있습니다.

```bash
uv run order-ui-agent
```

<http://127.0.0.1:8000>에 접속해 **관리자 모드**를 선택합니다. 데모 DB는 연구용 과제 DB와 구조가 달라 참가자 실험 대신 관리자 화면에서 사용합니다. 조회 DB와 대화 상태 DB는 별도 파일입니다.

## 처음 해볼 질문

| 질문 | 합성 데이터의 정답 |
|---|---|
| 전체 주문은 몇 건이야? | 8건 |
| 배송 실패 주문은 몇 건이야? | 3건 |
| 배송 실패 주문을 상품별로 집계해줘 | Alpha 2건, Beta 1건 |

먼저 프롬프트 모드에서 질문하고, Agent2UI 모드에서는 동일 질문의 기간·필터·집계 기준을 확인한 후 실행합니다. 필요하면 조건을 수정해 두 방식의 차이를 살펴보세요. 위 값은 데이터의 정답이며 모델의 성공률을 의미하지 않습니다. 실제 API를 이용한 응답은 모델 설정과 생성 결과에 따라 달라질 수 있습니다.

README와 화면 갤러리의 캡처는 기존 주문 데이터의 예시입니다. 합성 데모의 숫자·스키마와 다릅니다.

API 키 없이 SQL 정답만 확인할 수도 있습니다.

```bash
python3 - <<'PY'
import sqlite3
with sqlite3.connect('file:Data/demo.sqlite?mode=ro', uri=True) as db:
    print(db.execute('SELECT COUNT(*) FROM orders').fetchone())
    print(db.execute("SELECT COUNT(*) FROM orders WHERE status='failed'").fetchone())
    print(db.execute("SELECT product_name, COUNT(*) FROM orders WHERE status='failed' GROUP BY product_name ORDER BY product_name").fetchall())
PY
```

## 본인 데이터 연결

`.env.example`을 바탕으로 `ORDER_UI_DB_PATH`를 지정하고, `SCHEMA_SUMMARY_PATH`, `SCHEMA_VALUE_ALIASES_PATH`, `ANALYSIS_SEMANTICS_PATH`를 실제 DB에 맞게 설정합니다. 기본 `Data/docs/`와 `Data/migrations/`는 원래 주문 도메인용입니다. 임의의 DB에 기존 분석 뷰 SQL을 적용하지 마세요. 실험 기능을 사용할 때는 `app/experiment/tasks.json`의 과제도 변경해야 합니다.

## 자주 생기는 문제

| 현상 | 확인할 내용 |
|---|---|
| `SQLite database not found` / 시작 점검 실패 | 데모 생성 여부, 루트 디렉터리에서 실행했는지, `ORDER_UI_DB_PATH` |
| API 인증·모델 오류 | 키, API 사용 권한, 두 모델 설정 |
| 이전 주문 도메인의 컬럼을 참조함 | 데모용 스키마·별칭·의미 규칙 경로 3개와 서버 재시작 여부 |
| 계획 버전 충돌 | 최신 검토 화면에서 수정·확정 |
| 기대한 답과 다름 | 계획의 집계 단위·필터와 실행 SQL 확인. 합성 데이터 정답과 비교 |

## API 키 없는 검증

```bash
uv run pytest tests/execution -q
```

검증은 임시 DB와 대체 LLM 응답을 이용합니다. 실제 LLM 품질이나 브라우저 전체 동작을 보증하는 테스트는 아닙니다.
