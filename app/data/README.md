# `app/data` · 조회 데이터베이스 경로

## 1. 이 폴더의 역할

> **한눈에 보기** · 분석할 DB 파일의 위치를 정합니다. 분석 데이터와 대화·화면 상태를 저장하는 DB는 따로 사용합니다.

**기본 흐름:** 데이터 설정 읽기 → DB 경로 확인 → 다른 모듈에 제공

## 2. 해결하려는 문제

실행 위치에 따라 다른 DB를 찾거나 분석 데이터에 상태 테이블을 만들면 예상과 다른 데이터를 사용할 수 있습니다. 조회 DB 경로를 명확히 정하고 상태 저장소와 분리합니다.

## 3. 핵심 기술

조회용 DB 경로를 공통으로 결정합니다. DATA_PROFILE_PATH가 있으면 스키마·별칭·업무 의미 설정까지 먼저 적용한 뒤 DEFAULT_DB_PATH를 정합니다. 조회 DB와 런타임 상태 DB를 분리하여 분석 데이터에 상태 테이블을 만들지 않도록 합니다.

## 4. 핵심 함수와 실제 코드

### 주요 함수·클래스

| 함수·클래스 | 구체적인 역할 | 관련 기술 |
|---|---|---|
| `_resolve_default_database_path` | 명시 경로 또는 기본 DB 후보 선택 | 환경 설정 우선순위 |
| `ensure_database_ready` | 파일 존재와 읽기 전용 연결 점검 | 조기 실패 |
| `PROJECT_ROOT` | 파일 깊이와 무관한 공통 기준 경로 | 경로 안정성 |

### 핵심 코드: _resolve_default_database_path

여러 모듈이 서로 다른 DB를 고르는 문제를 줄입니다.

**동작:** 명시 경로를 우선하고 없으면 Data/database.sqlite, 이후 상태 DB를 제외한 sqlite 후보 중 큰 파일을 고릅니다.

**설계:** 모듈 초기화 시 결정되는 경로 선택입니다. 지정한 프로필과 공통 DB 경로를 실행·탐색 계층이 공유합니다.

**예:** 상대 ORDER_UI_DB_PATH는 프로젝트 루트 기준으로 해석됩니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [app/data/database.py](database.py#L16). 아래는 실제 코드의 16~36행 발췌이며 앞뒤는 생략했습니다.

```python
def _resolve_default_database_path() -> Path:
    configured = os.environ.get("ORDER_UI_DB_PATH")
    if configured:
        path = Path(configured).expanduser()
        return path if path.is_absolute() else PROJECT_ROOT / path

    data_dir = PROJECT_ROOT / "Data"
    conventional = data_dir / "database.sqlite"
    if conventional.is_file():
        return conventional

    state_path = Path(
        os.environ.get("ORDER_UI_STATE_DB_PATH", data_dir / "runtime_state.sqlite")
    ).expanduser()
    candidates = [
        path for path in data_dir.glob("*.sqlite")
        if path.is_file() and path.resolve() != state_path.resolve()
    ]
    if candidates:
        return max(candidates, key=lambda path: path.stat().st_size)
    return conventional
```

</details>

### 다른 기능과 연결되는 순서

core.data_profile을 적용한 뒤 경로 상수를 schema_tools·sql_builder 등이 가져옵니다. 실제 조회용 authorizer와 SQL 안전성은 execution/sql에서 적용하며 이 모듈은 DB 생성이나 마이그레이션을 자동 수행하지 않습니다.

## 5. 구현 결과와 한계

**현재 구현:** 설정과 프로필에서 조회 DB 경로를 결정하고 사용할 파일이 있는지 확인합니다.

여러 DB가 있는 환경에서 파일 크기 선택은 업무 의미를 보장하지 않으므로 ORDER_UI_DB_PATH 또는 프로필을 명시해야 합니다. 경로가 모듈 import 시 정해져 실행 중 환경 변수를 바꾼다고 모든 모듈에 즉시 반영되지는 않습니다.

관련 검증: [test_data_profile.py](../../tests/test_data_profile.py).

<details>
<summary>파일 목록과 관련 문서 보기</summary>

### 보충 안내

분석 대상 SQLite의 경로를 결정하고 파일이 읽을 수 있는 DB인지 확인합니다.

### 주요 파일

| 파일 | 역할 |
|---|---|
| [database.py](database.py) | 조회 DB 경로 선택과 SQLite 파일 준비 상태 확인. |

### 함께 읽기

- [앱 전체 구조](../README.md)
- [프로젝트 소개](../../README.md)

</details>
