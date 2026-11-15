# 운영·검증·공개 소스 도구

> **한눈에 보기** · 데모 데이터 준비, 새 DB 설정 생성, 공개용 소스 정리, 개발용 검증에 쓰는 도구입니다. 필요한 스크립트만 골라 실행합니다.

**기본 흐름:** 목적에 맞는 스크립트 선택 → 입력 준비 → 생성·검증 결과 확인

## 핵심 개념과 동작

운영 스크립트는 합성 데모 생성, 실제 스키마로부터 프로필 초안 생성, 허용 목록 기반 공개 소스 묶음과 오프라인 검증을 제공합니다. 평가 SQL은 런타임 모델의 입력 데이터와 구분하며, 실모델을 거치는 흐름 점검과 등록 지표 비교도 구분합니다.

### 주요 함수·클래스

| 함수·클래스 | 구체적인 역할 | 관련 기술 |
|---|---|---|
| `create_profile` | PK/FK·컬럼·타입으로 메타데이터 초안 생성 | 스키마 introspection |
| `create_database` | 작은 합성 데모 DB 생성 | 재현 가능한 입력 |
| `public_content` | 출력·비공개 링크를 제거한 공개용 내용 생성 | 공개용 변환 |
| `validate` | 등록 지표 결과를 독립 참조 SQL과 비교 | 오프라인 기준 비교 |
| `run_mode` | 개발 서버의 과제 질문 흐름 실행 | 서비스 smoke test |

### 핵심 코드: create_profile

새 도메인의 메타데이터를 기존 프로필을 덮지 않고 준비합니다.

**동작:** DB 파일과 출력 경로를 확인하고 읽기 전용으로 스키마를 읽어 PK/FK·컬럼만 수집합니다.

**설계:** SQLite PRAGMA 기반 introspection입니다. 원자료·API 키·샘플 행을 프로필에 복사하지 않고 사람이 업무 의미를 보완할 출발점을 만듭니다.

**예:** --database sample.sqlite --output new-profile은 profile.json·스키마 설명·별칭·의미 설정을 만듭니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [scripts/create_data_profile.py](create_data_profile.py#L10). 아래는 실제 코드의 10~29행 발췌이며 앞뒤는 생략했습니다.

```python
database, output = Path(database).resolve(), Path(output).resolve()
if not database.is_file():
    raise ValueError('Database does not exist')
if output.exists() and any(output.iterdir()):
    raise ValueError('Output directory must be new or empty; existing profiles are never overwritten')
# Inspect first, then write the complete profile. No sample rows or API keys
# are copied; PK/FK declarations, columns, and types are the only evidence.
with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as conn:
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    schemas, foreign_keys = {}, {}
    for table in tables:
        quoted = '"' + table.replace('"', '""') + '"'
        schemas[table] = conn.execute(f'PRAGMA table_info({quoted})').fetchall()
        foreign_keys[table] = conn.execute(f'PRAGMA foreign_key_list({quoted})').fetchall()
entities, roles, relationships = {}, [], []
for table, columns in schemas.items():
    pks = [c[1] for c in columns if c[5]]
    # Composite keys remain table-grain metadata, not individually unique.
    if len(pks) == 1:
        entities[table] = {'semantic_terms':[table], 'identifier_fields':pks}
```

</details>

### 핵심 코드: public_content

연구 노트북 소스와 비공개 실행 결과를 구분합니다.

**동작:** 노트북의 코드 셀 출력·실행번호·메타데이터·첨부를 정리하고 특정 비공개 링크 패턴을 치환합니다.

**설계:** 허용 목록 아카이브와 파일별 공개 변환입니다. 원본 로컬 자료를 건드리지 않고 배포용 사본만 정리합니다.

**예:** ipynb의 outputs는 []가 되고 실행 횟수는 null인 공개 내용이 반환됩니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [scripts/export_public.py](export_public.py#L36). 아래는 실제 코드의 36~54행 발췌이며 앞뒤는 생략했습니다.

```python
if path.suffix == ".ipynb":
    notebook = json.loads(path.read_text(encoding="utf-8"))
    for cell in notebook["cells"]:
        source = "".join(cell.get("source", []))
        source = re.sub(r"https://docs\.google\.com/spreadsheets/[^\s\"']+", "private-survey-source", source)
        source = re.sub(r"REANALYSIS_THREADS = \{[^}]*\}", "REANALYSIS_THREADS = set(common.REANALYSIS_THREADS)", source)
        cell["source"] = source.splitlines(keepends=True)
        cell["metadata"] = {}
        cell.pop("attachments", None)
        if cell["cell_type"] == "code":
            cell["outputs"] = []
            cell["execution_count"] = None
    notebook["metadata"] = {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python"},
    }
    return (json.dumps(notebook, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
if path.name == "analysis_common.py":
    source = path.read_text(encoding="utf-8")
```

</details>

### 다른 기능과 연결되는 순서

새 프로필은 create_data_profile.py를 실행한 뒤 사람이 의미를 보완하고 DATA_PROFILE_PATH로 선택합니다. export_public.py는 app/tests의 허용 확장자와 FILES 목록만 zip에 넣습니다. 검증 스크립트는 명시적으로 실행할 때만 서버 또는 DB를 사용합니다.

```bash
uv run python scripts/create_data_profile.py --database path/to/data.sqlite --output path/to/new-profile
uv run python scripts/create_demo_db.py --output Data/demo.sqlite
uv run python scripts/export_public.py
```

### 확인한 범위와 한계

프로필의 업무 용어·시간 기준·지표 분모는 자동으로 정확히 추론하지 않습니다. export_public의 치환은 알려진 패턴만 다루므로 모든 개인정보 탐지를 보장하지 않습니다. validate_registered_metrics는 LLM을 호출하지 않으며 전체 자연어 해석 정확도로 보고하면 안 됩니다.

관련 검증: [test_data_profile.py](../tests/test_data_profile.py), [test_registered_metrics.py](../tests/execution/test_registered_metrics.py).
