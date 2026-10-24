# A2UI 사용자 연구 분석 노트북

프롬프트 방식과 Agent2UI 방식의 사용자 경험 및 행동 로그를 분석하는 **Jupyter 노트북 7개**입니다. 주문 이벤트 DB를 조회하는 앱 코드와 별도의 연구 분석 자료입니다.

공개본은 분석 셀과 설명을 제공하며, 셀 출력·실행 번호·원자료 링크·로컬 개인 경로 등 실행 기록을 제거했습니다. 원본 설문·참가자 목록·행동 로그와 실행 시 생성되는 결과 파일은 포함하지 않습니다. 별도로 제공받은 [실험 안내문과 집계 결과 문서](../../docs/experiments/README.md)는 원본 및 Markdown 보존본으로 공개하며, 문서 내부의 수치·해석 불일치도 그곳에 안내합니다. **원자료 없이 전체 실행할 수 없으며, 공개된 결과의 독립 재현을 보장하지 않습니다.**

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

이 폴더는 분석 방법을 살펴보기 위한 소스 공개입니다. 개인별 응답·기록, 출력 셀, 로컬 분석 산출물, 설문 공유 링크를 포함하지 않습니다. 별도 보존한 제공 결과표는 [실험 자료](../../docs/experiments/README.md)에서 확인할 수 있습니다. 데이터 제공 없이 새 연구의 통계 결과가 생성되는 예제는 아니며, 주문 DB나 합성 앱 데모로 설문을 대체할 수 없습니다.
