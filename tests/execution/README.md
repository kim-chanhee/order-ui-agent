# SQL 실행 회귀·통합 테스트

> **한눈에 보기** · 잘못된 SQL이 차단되고 올바른 조회가 실행되는지 검사합니다. 실제 사용자 DB 대신 임시 SQLite를 사용합니다.

**기본 흐름:** 임시 DB·모델 응답 준비 → 검사·조회 → 결과 확인

프로젝트 루트에서 실행합니다.

```bash
uv run pytest -q tests/execution
```

테스트는 임시 SQLite DB를 생성하며 사용자 데이터와 외부 LLM API를 사용하지 않습니다.
서비스 통합 테스트는 LLM 응답만 대체하고 스키마 탐색·SQL 검사·DB 실행·응답 조립은 실제로 수행합니다.

- 고유 주문 건수, 원시 결과, 행 수 제한
- DB 변경·다중 문장·미검사 SQL·미확인 스키마 차단
- 계획과 다른 건수 단위, 요청한 표시 이름 누락, 근거 없는 필터 차단
- 상대 기간의 데이터 기준 날짜와 마지막 날 전체 포함
- 실행 직전 스키마·계획 재검증
- Baseline 즉시 실행과 A2UI 확정 실행 서비스

## 핵심 개념과 동작

실행 테스트는 안전성 검사부터 실제 임시 SQLite 조회까지 연결합니다. SQL Agent 통합에서는 LLM 응답만 대체하고 검사 Tool·DB·응답 조립을 실제 사용하여 잘못된 계약이 데이터 조회 전에 또는 결과 검사에서 차단되는지 확인합니다.

### 주요 함수·클래스

| 함수·클래스 | 구체적인 역할 | 관련 기술 |
|---|---|---|
| `pipeline` | 공유 상태의 검사·실행 Tool 구성 | 통합 테스트 도우미 |
| `test_physical_tables_respect_query_scopes_without_changing_tree` | 중첩·재귀 CTE의 물리 참조와 원본 불변 검사 | 매개변수화 테스트 |

### 핵심 코드: test_physical_tables_respect_query_scopes_without_changing_tree

문자열 입력 경로와 AST 재사용 경로가 같은 결과를 내는지 확인합니다.

**동작:** 트리 SQL을 저장한 뒤 두 추출 함수와 호출 후 원본 SQL을 비교합니다.

**설계:** 여러 SQL을 같은 검증에 넣는 pytest parametrize 방식입니다. 함수 통합과 스코프 수정이 이름·원본 트리를 바꾸는 회귀를 탐지합니다.

**예:** 재귀 CTE 이름은 실제 테이블에 포함되지 않고 원래 테이블 이름은 보존됩니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [tests/execution/test_sql_ast.py](test_sql_ast.py#L48). 아래는 실제 코드의 48~53행 발췌이며 앞뒤는 생략했습니다.

```python
def test_physical_tables_respect_query_scopes_without_changing_tree(sql, expected):
    tree = parse_sql_ast(sql)
    original = tree.sql()
    assert physical_tables_from_tree(tree) == expected
    assert tree.sql() == original
    assert extract_physical_tables(sql) == expected
```

</details>

### 다른 기능과 연결되는 순서

checker → executor → successes 또는 오류를 비교합니다. 등록 지표 테스트는 독립 도메인 임시 데이터로 분모·부분집합 0 그룹까지 검증하고 JOIN 테스트는 역할 설정으로 CTE 투영 충돌을 확인합니다.

### 확인한 범위와 한계

대체 모델의 예정된 Tool 호출을 검증하므로 실모델이 항상 올바른 도구를 선택한다는 증거는 아닙니다. DB 성능·운영 권한·모든 SQL 동등식을 포괄하지 않습니다.

관련 검증: [test_sql_tools.py](test_sql_tools.py), [test_join_contract.py](test_join_contract.py), [test_registered_metrics.py](test_registered_metrics.py).
