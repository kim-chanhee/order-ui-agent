# 데이터 안내 · 어떤 데이터로 무엇을 분석하나요?

> **한눈에 보기** · 주문 분석용 공개 데이터와 사용자 연구용 비공개 자료를 구분합니다. 필요한 DB의 출처와 준비 방법도 설명합니다.

**기본 흐름:** 데이터 출처 확인 → DB 준비 → 스키마·업무 설정 연결

이 프로젝트는 **주문 업무를 표현하는 공개 이벤트 로그**와 **인터페이스를 평가한 비공개 연구 자료**를 구분합니다. GitHub에는 DB 파일 대신 출처와 구조 설명, 스키마 설정, 분석 코드를 제공합니다. 필요한 DB는 원 배포처에서 직접 준비합니다.

| 구분 | 내용 | 저장소에 포함하는 것 |
|---|---|---|
| 주문·물류 데이터 | 주문 접수부터 결제·포장·배송까지의 시뮬레이션 이벤트 | 출처·구조 안내, `docs/` 설정, `migrations/` SQL |
| A2UI 사용자 연구 | 프롬프트 UI와 Agent2UI 사용 후의 설문·상호작용 | [분석 노트북과 공통 코드](A2UI/README.md) |
| 앱 실행 상태 | 대화·계획 화면 버전·실험 진행 상태 | 실행 시 로컬 생성, 파일은 미포함 |

## 1. 주문 데이터의 정확한 출처

- **자료명:** Order Management Object-centric Event Log in OCEL 2.0 Standard
- **제작자:** Benedikt Knopp, Wil M. P. van der Aalst · RWTH Aachen
- **고정 버전:** v3, 2026-01-26 공개
- **배포·인용:** [Zenodo 레코드](https://zenodo.org/records/18373906) · [DOI: 10.5281/zenodo.18373906](https://doi.org/10.5281/zenodo.18373906)
- **업무 과정·모델 설명:** [OCEL 공식 Order Management 안내](https://www.ocel-standard.org/event-logs/simulations/order-management/)
- **다운로드 파일:** 위 고정 레코드의 Files 영역에서 `order-management.sqlite` 선택. JSON·XML도 제공하지만 이 앱은 SQLite를 조회합니다.

이 자료는 **CPN Tools 시뮬레이션으로 생성한 인공 이벤트 로그**입니다. 실제 기업의 고객 거래 자료나 본 프로젝트가 수집한 참가자 데이터가 아닙니다. 공식 설명 기준 이벤트 유형 11개, 객체 유형 6개, 이벤트 21,008개, 객체 10,840개로 구성됩니다. 출처·규모·버전은 [원 배포 레코드](https://zenodo.org/records/18373906)에 근거합니다.

## 2. 쉬운 예로 이해하는 OCEL

보통 주문표는 “한 행 = 주문 하나”라고 생각하기 쉽습니다. 이 데이터는 **한 행의 주문 요약이 아니라, 업무 과정에서 발생한 사건과 참여 객체의 연결**을 기록합니다.

예를 들어 고객이 물품을 주문하면 주문 접수·결제·물품 수집·포장·배송 사건이 생깁니다. 한 패키지에 여러 주문의 물품이 들어갈 수 있고, 한 주문이 여러 패키지로 나뉠 수도 있습니다. 따라서 주문·패키지·물품을 같은 단위로 집계하면 안 됩니다. [공식 과정 설명](https://www.ocel-standard.org/event-logs/simulations/order-management/)

| 객체 | 의미 | 질문 예 |
|---|---|---|
| orders | 고객의 주문 | 배송 실패와 연결된 고유 주문은 몇 건인가? |
| customers | 주문한 고객 | 고객별 주문 건수는? |
| items | 개별 물품 | 실패 주문에 포함된 개별 물품은? |
| products | 상품 종류 | 상품명별 물품 수는? |
| packages | 포장·배송 단위 | 실패한 패키지가 이후 배송 완료됐는가? |
| employees | 영업·창고·배송 업무 담당자 | 담당자별 이벤트는? |

`items`는 개별 물품, `products`는 상품 종류를 나타냅니다. 같은 상품 여러 개와 서로 다른 상품 종류의 개수를 구분해야 합니다.

## 3. SQLite 내부를 읽는 방법

| 테이블 | 역할 |
|---|---|
| `event` | 사건 ID와 사건 유형 |
| `event_*` | 유형별 사건의 시각·속성 |
| `object` | 객체 ID와 객체 유형 |
| `object_*` | 유형별 객체 속성·변경 이력 |
| `event_object` | 사건에 참여한 객체 연결 |
| `object_object` | 주문–물품, 물품–상품 등 객체 사이의 연결 |
| `event_map_type`, `object_map_type` | 업무 유형과 저장 테이블 이름의 대응 |

관계의 의미는 `ocel_qualifier`와 연결된 양쪽 객체 유형을 함께 확인합니다. 예를 들어 로컬 스키마의 주문–물품 연결은 `comprises`, 물품–상품 연결은 `is a`를 사용합니다. 컬럼과 실제 값은 내려받은 파일의 스키마로 확인해야 합니다.

## 4. 이 시스템이 분석하는 방식

실험에 사용한 로컬 DB에는 원본 OCEL 위에 분석용 테이블·뷰가 추가되어 있습니다. **이 분석 계층은 프로젝트의 가공 결과이며 Zenodo 원본에 모두 포함되어 있다고 가정하면 안 됩니다.**

| 프로젝트 분석 계층 | 주된 용도 |
|---|---|
| `analysis_order_customers` | 주문과 고객의 연결 |
| `analysis_order_events` | 주문 생명주기 이벤트 |
| `analysis_shipment_status_orders` | 배송 상태 사건과 주문·패키지·고객 연결 |
| `analysis_item_events` | 개별 물품 사건과 주문·상품 연결 |
| `analysis_daily_event_counts` | 날짜·유형별 집계 |
| `analysis_order_item_products` | 주문–개별 물품–상품명 연결 |
| `analysis_failed_delivery_orders` | 배송 실패와 연결된 주문 |
| `analysis_failed_delivery_items` | 실패 주문의 물품과 상품명 |

[스키마 설명](docs/schema_summary.md), [값 별칭](docs/value_aliases.json), [분석 의미 규칙](docs/analysis_semantics.json)이 사용자 표현과 DB 의미를 연결합니다.

### 집계할 때 주의할 점

- **실패 이벤트 수 ≠ 실패 주문 수:** 한 주문에 여러 사건이 연결되므로 고유 주문은 `COUNT(DISTINCT order_id)`로 셉니다.
- **상품 종류 수 ≠ 개별 물품 수:** 상품명과 내부 물품 ID를 구분합니다.
- **주문 물품 전체 ≠ 특정 실패 사건에 직접 연결된 물품:** 질문의 모집단에 맞춰 관계를 선택합니다.
- **최근 N일의 기준은 데이터의 최신 날짜:** 오늘 날짜가 아니라, 해당 설정의 기준 테이블 최신 날짜를 사용합니다.

## 5. DB 파일 없이 배포하는 이유와 준비 방법

이 저장소는 분석 대상 파일을 재배포하기보다 **원 배포처·버전·가공 계층을 명확히 설명**하는 방식을 사용합니다. 내려받은 파일과 런타임 상태는 로컬에 보관하며 `.gitignore`가 SQLite 파일을 제외합니다.

1. [고정 Zenodo 레코드](https://zenodo.org/records/18373906)에서 `order-management.sqlite`를 내려받습니다.
2. 로컬 `Data/order-management.sqlite`로 저장합니다. 배포 페이지의 파일 체크섬과 인용·이용 조건을 확인합니다.
3. `.env.example`을 참고해 아래처럼 경로를 지정합니다.

```dotenv
ORDER_UI_DB_PATH=Data/order-management.sqlite
ORDER_UI_STATE_DB_PATH=Data/runtime_state.sqlite
```

**원본 다운로드만으로 기존 실험 화면을 그대로 재현할 수는 없습니다.** 현재 공개된 [001_analysis_views.sql](migrations/001_analysis_views.sql)은 3개 뷰 정의이며, 그중 2개는 별도로 가공된 `analysis_shipment_status_orders`에 의존합니다. 나머지 분석 테이블의 전체 생성 절차는 아직 공개 소스에 포함되지 않았습니다. 원본만 사용할 때는 실시간 스키마에 맞춰 `SCHEMA_SUMMARY_PATH`, `SCHEMA_VALUE_ALIASES_PATH`, `ANALYSIS_SEMANTICS_PATH`를 조정해야 합니다. 이 문서가 원본 다운로드와 가공 DB 재현을 구분하는 이유입니다.

앱 동작을 간단히 확인하려면 기존 [합성 데이터 데모](../docs/getting-started.md)를 선택할 수 있습니다. 데모 DB도 코드 실행 시 로컬에서 생성되며 GitHub에 바이너리를 저장하지 않습니다.

## 6. A2UI 연구 자료는 별도 데이터입니다

[Data/A2UI](A2UI/README.md)의 노트북은 위 주문 로그 자체가 아니라, **인터페이스 비교 실험에서 수집한 설문과 행동 로그**를 분석합니다. 설문 원자료·참가자 목록·개별 로그는 배포하지 않으며, 노트북은 출력이 제거된 분석 코드로 제공합니다. 필요한 입력 자료와 실행 순서는 해당 폴더 안내를 참고하세요.

## 핵심 개념과 동작

OCEL은 사건(Event), 객체(Object), 사건-객체 및 객체-객체 관계를 분리하는 데이터 표현입니다. 한 사건이 여러 객체와 연결되어 JOIN 뒤 행 수가 늘 수 있으므로 테이블 행 수와 대상 엔터티의 고유 개수를 구분합니다. 새로운 도메인에서는 키와 관계의 선언을 먼저 읽고 시간 기준·업무 상태·집계 단위는 별도로 설정합니다.

### 주요 함수·클래스

| 함수·클래스 | 구체적인 역할 | 관련 기술 |
|---|---|---|
| `create_profile` | 실제 PK/FK에서 프로필 초안 생성 | 메타데이터 추출 |
| `apply_data_profile` | 조회 DB·상태 DB·설명·별칭·의미 설정 동시 선택 | 도메인 격리 |

### 핵심 코드: create_profile

복합키의 한 컬럼을 고유 엔터티 키로 오인하는 것을 피합니다.

**동작:** 테이블 PK 목록이 한 개일 때만 엔터티 식별자 역할로 선언하고 FK도 대상 단일 PK를 확인합니다.

**설계:** PK/FK 선언을 근거로 하는 보수적 역할 추출입니다. 행 단위와 엔터티 단위를 구분해 자동 추정 범위를 제한합니다.

**예:** 두 컬럼 복합 PK는 각 컬럼을 개별 고유 키로 자동 등록하지 않습니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [scripts/create_data_profile.py](../scripts/create_data_profile.py#L24). 아래는 실제 코드의 24~39행 발췌이며 앞뒤는 생략했습니다.

```python
entities, roles, relationships = {}, [], []
for table, columns in schemas.items():
    pks = [c[1] for c in columns if c[5]]
    # Composite keys remain table-grain metadata, not individually unique.
    if len(pks) == 1:
        entities[table] = {'semantic_terms':[table], 'identifier_fields':pks}
        roles.append({'table':table, 'field':pks[0], 'entity':table})
    for fk in foreign_keys[table]:
        target, source_field, target_field = fk[2:5]
        target_pks = [c[1] for c in schemas.get(target, []) if c[5]]
        if target_field is None and len(target_pks) == 1:
            target_field = target_pks[0]
        if target_field and len(target_pks) == 1 and target_field in target_pks:
            roles.append({'table':table,'field':source_field,'entity':target})
        relationships.append({'name':f'{table}_{source_field}_to_{target}', 'table':table,
            'source_field':source_field,'target_table':target,'target_field':target_field})
```

</details>

### 다른 기능과 연결되는 순서

원본 DB 준비 → 필요 시 분석 뷰 준비 → 스키마·별칭·업무 의미 설정 → 앱 시작 점검 → 읽기 전용 분석 순서입니다. 앱의 합성 데모와 사용자 연구 설문은 대체 가능한 데이터가 아닙니다.

### 확인한 범위와 한계

프로필 생성은 DB의 데이터 행을 복사하지 않지만 PK/FK가 없거나 잘못 선언되어 있으면 자동 역할 근거가 부족합니다. 원본과 가공 계층의 동일성·갱신 상태는 별도로 확인해야 합니다.

관련 검증: [test_data_profile.py](../tests/test_data_profile.py).
