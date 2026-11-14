# 새 데이터 연결과 수정 안내

SQLite 데이터와 그 데이터의 설명·별칭·의미 설정을 **하나의 프로필**로 선택합니다. 기존 주문 데이터의 설정이 새 데이터에 섞이지 않도록 합니다. DB를 교체하면 서버를 재시작하세요.

## 1. 프로필 생성

프로젝트 루트에서 실행합니다.

```bash
uv run python scripts/create_data_profile.py \
  --database "/path/to/new.sqlite" \
  --output Data/profiles/my-data
```

생성기는 실제 테이블·뷰·컬럼·PK·FK 선언만 읽습니다. 샘플 행이나 API 키를 복사하지 않고 원본 DB를 수정하지 않습니다. 기존 프로필 폴더는 덮어쓰지 않습니다.

| 생성 파일 | 수정할 내용 |
|---|---|
| `profile.json` | DB와 관련 파일 경로. 경로는 프로필 파일 위치 기준입니다. |
| `schema_summary.md` | 업무 용어, 테이블의 행 단위, 상태의 의미, 필요한 관계 설명 |
| `value_aliases.json` | 사용자 표현과 실제 값의 대응. 예: `{"취소": ["cancelled"]}` |
| `analysis_semantics.json` | 식별자 역할, 날짜 기준, 관계와 등록 지표 |
| `runtime_state.sqlite` | 서버가 처음 실행할 때 만드는 별도 대화·실험 상태 DB |

업무 의미가 없는 새 DB에서는 생성된 메타데이터로 시작할 수 있지만, 날짜 기준과 상태·비율의 의미는 직접 확인해서 작성해야 합니다. FK 선언이 없는 DB는 조인 방향을 자동 확정하지 않습니다.

## 2. 프로필 선택

```bash
DATA_PROFILE_PATH=Data/profiles/my-data/profile.json uv run order-ui-agent
```

또는 `.env`에 `DATA_PROFILE_PATH`를 설정합니다. 프로필은 DB·상태 DB·설명·별칭·의미 설정 경로를 한 번에 적용하며 기존 개별 환경 변수보다 우선합니다. 프로필을 사용하지 않는 기존 개별 경로 설정도 유지합니다.

서버 시작 및 `/health`에서 설정에 적힌 날짜·키·등록 지표의 실제 컬럼 존재 여부를 검사합니다. 없는 컬럼을 참조하면 시작을 중단합니다. `/health` 성공은 API 잔액이나 모델 해석 정확도를 뜻하지 않습니다.

상태 DB를 프로필마다 분리하므로 이전 데이터의 대화·실험 상태를 재사용하지 않습니다. 로그는 상태 DB 옆 `logs/`에 생성됩니다. 별도 위치가 필요하면 `ORDER_UI_LOG_DIR`을 설정합니다.

## 3. 의미 설정

다음 항목은 필요할 때 추가합니다. 모든 항목을 채워야 하는 고정 양식은 아닙니다.

- `timeline_anchor`: 상대 기간의 기준 테이블·컬럼. 전체 데이터의 최댓값이 기준입니다.
- `entity_roles`: 엔터티 이름, 사용자 용어, 안정적인 식별자 필드. `book_key`처럼 `_id`가 아닌 키도 지원합니다.
- `column_roles`: 물리 테이블·컬럼이 식별하는 엔터티. 관계 한정 값에 따라 역할이 달라지면 `discriminator`와 `entities`를 지정합니다.
- `entity_relationships`: 명시적으로 확인한 관계. 생성기가 선언된 FK에서 초안을 만듭니다.
- `attribute_roles`: 이름·가격 등 속성 역할.
- `semantic_metrics`: 반복해서 사용하는 지표의 업무 정의.

예를 들어 주문 ID와 이벤트 ID는 모두 문자열이어도 서로 다른 역할입니다. `column_roles`를 바탕으로 SQL의 비교 키를 검사하며, CTE가 컬럼 이름을 바꾼 경우도 추적합니다. 알 수 없는 키 역할을 추측해서 동일하다고 확정하지는 않습니다.

`direct_event_link`, `parent_membership`, `entity_lifecycle`은 관계의 **의미 모드**입니다. 그 외 `relationship_scope`는 설정에 등록한 관계 이름만 사용할 수 있습니다. 임의의 관계 이름은 계속 거부합니다.

## 4. 등록 지표와 일반 SQL

일반 조회는 LLM이 라이브 스키마를 탐색해 SQL을 생성하고 검증합니다. 모집단과 부분집합이 명확히 반복되는 지표는 설정 기반 컴파일러를 사용할 수 있습니다. 두 입력 모드가 같은 선택·검증·실행 코드를 사용합니다.

등록 지표의 `population`과 `subset`에는 각각 `table`, `key`, `time_field`, 선택적인 동등 조건 `filters`를 지정합니다. 상위 정의에는 `kind`, `table`, `field`, `event_field`, `time_field`, `label`, `group_by`를 작성합니다. 비율은 `numerator`와 `denominator`의 의미 이름도 지정합니다. 실제 예제는 `Data/docs/analysis_semantics.json`과 주문과 무관한 합성 데이터 테스트 `tests/execution/test_registered_metrics.py`를 참고하세요.

컴파일러는 고유 키를 기준으로 모집단을 보존하는 LEFT JOIN을 만들고, 부분집합 건수와 비율을 계산합니다. 부분집합이 없는 그룹은 0으로 남습니다. 정답 수치나 과제 문장, 정답 SQL을 실행 코드에 넣지 않습니다. 결과에는 `execution_route=registered_metric`, SQL 모델 호출 0회를 명시합니다. 라우팅·계획 생성에는 여전히 모델이 필요합니다.

지원 범위는 단일 모집단·부분집합의 고유 키 건수/비율, 허용된 그룹·필터·기간·정렬·개수 제한입니다. 식별자 이름은 단순한 영문/숫자/밑줄 형식이어야 합니다. 지원하지 않는 추가 지표나 자유 텍스트 조건은 조용히 누락하지 않고 실행을 거부합니다. 이 컴파일러가 모든 분석을 처리하는 것은 아닙니다.

## 5. 코드 수정 위치

| 변경 목적 | 위치 |
|---|---|
| DB 교체·업무 설명·상태 코드·키·지표 변경 | 우선 프로필 파일 수정 |
| 프로필 로딩·검사 | `app/core/data_profile.py`, `app/core/startup_checks.py` |
| 질문의 분석 계획·UI 생성 | `app/planning/planner/` |
| 선택지·허용된 값 | `app/planning/option_catalog.py` |
| 관계 키 검사 | `app/execution/join_contract.py` |
| 설정 기반 모집단 지표 | `app/execution/registered_metrics.py` |
| 일반 SQL 생성 | `app/execution/fast_sql_agent.py` |
| SQL·결과 검증 | `sql_contract.py`, `result_contract.py`, `sql_tools.py` |
| 후속 질문과 실패 처리 | `app/chat/` |

의미 설정·별칭 변경은 파일 수정 시각으로 캐시를 갱신합니다. DB·의미 설정·검증 버전이 달라지면 SQL 사례 재사용 식별값도 바뀝니다. DB 경로를 변경하는 경우에는 서버 재시작이 필요합니다.

## 6. 변경 후 검증

```bash
uv run pytest tests -q
node --test tests/js/review-plan.test.js
```

새 DB에서는 직접 계산한 작은 정답 사례를 준비해 전체 건수, 그룹별 집계, 숫자 집계, FK 조인, 0건, 기간 경계, 후속 질문을 검증하세요. 네트워크 없는 테스트와 실제 모델을 거친 성공률은 별도로 기록합니다.
