# A2UI 사용자 연구 분석 노트북

> **한눈에 보기** · 사용자 설문과 행동 로그를 통계적으로 분석하는 노트북입니다. 앱의 SQL 실행 검사와는 별도의 연구 분석입니다.

**기본 흐름:** 연구 자료 준비 → 점수·집단 구성 → 통계 분석·가정 확인

프롬프트 방식과 Agent2UI 방식의 사용자 경험 및 행동 로그를 분석하는 **Jupyter 노트북 7개**입니다. 주문 이벤트 DB를 조회하는 앱 코드와 별도의 연구 분석 자료입니다.

공개본은 분석 셀과 설명을 제공하며, 셀 출력·실행 번호·원자료 링크·로컬 개인 경로 등 실행 기록을 제거했습니다. 원본 설문·참가자 목록·행동 로그와 기존 결과 파일은 포함하지 않습니다. **원자료 없이 전체 실행할 수 없으며, 공개된 결과의 독립 재현을 보장하지 않습니다.**

## 파일과 실행 순서

| 순서 | 노트북 | 역할 |
|---|---|---|
| 1 | [01 · 신뢰도](01_측정도구신뢰도_Cronbach_alpha.ipynb) | 다문항 척도의 Cronbach's alpha와 신뢰구간 |
| 2 | [02 · 기술통계](02_기술통계.ipynb) | 집단별 평균·표준편차 및 표·그림 |
| 3 | [03 · 상관분석](03_상관분석_Pearson.ipynb) | 사후 변수 사이의 Pearson 상관 |
| 4 | [04 · 이원분산분석](04_이원분산분석_UI유형x숙련도.ipynb) | UI 유형 × AI 리터러시 수준의 원자료 분석 |
| 5 | [04-1 · 가정 검정](04-1_사후설문_ANOVA_가정검정.ipynb) | 잔차 정규성·등분산성 등 진단 |
| 6 | [04-2 · 재분석](04-2_사후설문_ANOVA_가정검정과_BoxCox_재분석.ipynb) | 진단에 따른 Box–Cox 검토와 최종 결과 저장 |
| 7 | [05 · 로그 분석](05_Log분석.ipynb) | 행동 로그·민감도·완료율 분석 및 설문 결과 종합 |

[analysis_common.py](analysis_common.py)는 문항 정의, 점수 계산, 집단 구분, Type III ANOVA, 그림 설정을 공유합니다. 01~04-2는 각각 설문부터 읽으며, 05는 04-2의 결과와 검증 manifest를 사용합니다. 설문 또는 공통 모듈을 바꾸면 04-2를 다시 실행해야 합니다.

## 입력 데이터와 규칙

| 필요한 로컬 파일 | 용도 |
|---|---|
| `Data/A2UI/merged_survey.xlsx`의 `병합 데이터` 시트 | 설문 점수와 UI·AI 리터러시 집단 |
| `Data/logs/4_3_user_agent2ui_interactions_annotated.csv` | Agent2UI 행동 로그 |
| `Data/logs/4_3_user_baseline_interactions_annotated.csv` | Baseline 행동 로그 |
| `Data/analysis/participant_final_failure_reclassification.xlsx` | 과제 완료·실패 분류 |
| `Data/A2UI/results/survey_final_anova.csv` 및 manifest | 04-2가 생성하는 05용 입력 |

설문 열은 `참여자번호`, `인터페이스` 및 공통 모듈의 문항 접두어로 찾는 응답 열을 요구합니다. 인터페이스 값은 `Agent2UI 방식` 또는 `Baseline Prompt 방식`입니다. 코드에는 원 연구의 참가자 40명 및 과제 구조를 확인하는 조건이 포함되어 있어 다른 표본에 적용할 때 수정이 필요합니다. AI 리터러시는 사전 6문항 평균 6.0을 기준으로 집단을 구분합니다.

공개본 05의 사후 보정 스레드 목록은 개인정보 노출을 줄이기 위해 별도 로컬 `analysis_exclusions.json`에서 읽습니다. 이 파일은 배포하지 않습니다. 필요하면 다음 형식으로 연구별 목록을 준비합니다. 미설정 시 빈 목록이므로 원 연구와 같은 제외 결과를 의미하지 않습니다.

```json
{"reanalysis_threads": []}
```

## 실행 환경

```bash
uv sync --dev --locked
uv run python -m ipykernel install --user --name order-ui-agent --display-name "order-ui-agent"
```

Jupyter 지원 편집기에서 이 커널을 선택하고, 프로젝트 루트 또는 `Data/A2UI`를 작업 디렉터리로 설정합니다. 입력 자료를 준비한 뒤 위 순서대로 실행합니다. `figures/`와 `results/`는 실행 시 생성되며 공개 소스에서 제외됩니다.

현재 코드가 사용하는 `pandas`, `numpy`, `scipy`, `statsmodels`, `matplotlib`, `seaborn`, `pingouin`, `openpyxl` 등이 필요합니다. 프로젝트 개발 의존성과 Excel 읽기 엔진은 `uv sync --dev --locked`로 설치합니다.

별표 규칙은 공통 모듈에 정의되어 있습니다. `p < .05`와 `.05 < p < .10`을 구분하며, 경계값 .05와 .10에는 별표가 없습니다. 해석 시 유의 결과와 탐색적 경향을 구분해야 합니다.

## 원자료와 공개 코드의 구분

이 폴더는 분석 방법을 살펴보기 위한 소스 공개입니다. 개인별 응답·기록, 출력 셀, 이전 결과표, 설문 공유 링크를 포함하지 않습니다. 데이터 제공 없이 새 연구의 통계 결과가 생성되는 예제는 아니며, 주문 DB나 합성 앱 데모로 설문을 대체할 수 없습니다.

## 핵심 개념과 동작

먼저 설문 문항을 점수로 묶고, UI 방식과 숙련도에 따라 집단을 만듭니다. ANOVA(분산분석)로 집단 간 차이와 두 조건의 상호작용을 분석합니다.

Cronbach α는 문항의 일관성, Pearson 상관은 변수 간 선형 관계를 살펴보는 지표입니다. 잔차의 분포와 집단별 분산도 확인하며, 필요한 경우 Box–Cox 변환 후 다시 분석합니다. 이 결과는 앱 실행 정확도 검사와 구분합니다.

### 주요 함수·클래스

| 함수·클래스 | 구체적인 역할 | 관련 기술 |
|---|---|---|
| `item_scores` | 문항 열을 찾아 수치화하고 결측 거절 | 척도 점수 전처리 |
| `make_design` | UI와 사전 리터러시 기준 집단 구성 | 연구 설계 |
| `fit_anova` | Sum coding과 Type III ANOVA | 선형 모형 |
| `test_residual_assumptions` | 잔차 Shapiro·집단 Levene 검사 | 모형 진단 |
| `survey_hash / module_hash` | 입력과 공통 분석 코드 식별 | 재현 근거 |

### 핵심 코드: fit_anova

UI와 숙련도의 주효과·상호작용을 같은 공통 모형으로 추정합니다.

**동작:** 설계표 사본에 score를 추가하고 OLS를 적합한 뒤 Type III ANOVA 표를 반환합니다.

**설계:** statsmodels와 Sum coding을 사용하는 선형 모형입니다. 여러 노트북이 서로 다른 모형식으로 계산되는 것을 줄입니다.

**예:** 설계 DataFrame과 점수 배열을 받아 model·model_data·anova_table을 반환합니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [Data/A2UI/analysis_common.py](analysis_common.py). 아래는 로컬 원본 코드의 99~103행 발췌이며 앞뒤는 생략했습니다. 공개용 변환본에서는 행 번호가 달라질 수 있습니다.

```python
def fit_anova(design, values):
    data = design.copy()
    data['score'] = np.asarray(values, dtype=float)
    model = smf.ols(MODEL_FORMULA, data=data).fit()
    return model, data, anova_lm(model, typ=3)
```

</details>

### 핵심 코드: test_residual_assumptions

ANOVA 결과 해석에 필요한 잔차 분포·집단 분산 조건을 진단합니다.

**동작:** 모형 잔차에 Shapiro를 적용하고 집단별 잔차에 median Levene를 계산합니다.

**설계:** SciPy 통계 검정과 index 정렬입니다. 결과 유의확률과 별도로 모형 가정에 대한 근거를 보존합니다.

**예:** 반환값은 Shapiro W·p, Levene F·p를 담은 딕셔너리입니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [Data/A2UI/analysis_common.py](analysis_common.py). 아래는 로컬 원본 코드의 113~118행 발췌이며 앞뒤는 생략했습니다. 공개용 변환본에서는 행 번호가 달라질 수 있습니다.

```python
def test_residual_assumptions(model, model_data):
    residuals = pd.Series(model.resid.to_numpy(), index=model_data.index)
    shapiro = stats.shapiro(residuals)
    levene = stats.levene(*[residuals.loc[model_data['집단'].eq(g)].to_numpy() for g in GROUP_ORDER], center='median')
    return {'Shapiro W': shapiro.statistic, '정규성 p': shapiro.pvalue,
            'Levene F': levene.statistic, '등분산성 p': levene.pvalue}
```

</details>

### 다른 기능과 연결되는 순서

01 신뢰도 → 02 기술통계 → 03 상관 → 04 모형 → 04-1 가정 → 04-2 조건부 재분석 → 05 행동 로그·종합 순으로 구성됩니다. 공통 문항 매핑·집단 기준과 manifest가 후속 분석에 영향을 줍니다.

### 확인한 범위와 한계

참가자 수·집단 경계·문항 접두어는 원 연구를 전제합니다. 가정 검사 p값 하나로 인과효과나 모형 타당성을 보장하지 않으며 다중 비교·표본 설계에 대한 해석이 필요합니다. 이번 문서 작업은 비공개 설문·행동 로그를 실행하거나 통계 결과를 재생성하지 않았습니다.
