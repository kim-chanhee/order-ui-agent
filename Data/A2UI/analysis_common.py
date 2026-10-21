"""01–05 노트북의 공통 정의. 개별 노트북은 각각 독립적으로 실행할 수 있다."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd
from scipy import stats
import statsmodels.formula.api as smf
from statsmodels.stats.anova import anova_lm

A2UI_DIR = Path(__file__).resolve().parent
SURVEY_FILE = A2UI_DIR / 'merged_survey.xlsx'
FIGURE_DIR = A2UI_DIR / 'figures'
RESULT_DIR = A2UI_DIR / 'results'
# Private study-specific thread IDs must be supplied locally; never committed.
EXCLUSIONS_FILE = A2UI_DIR / 'analysis_exclusions.json'
REANALYSIS_THREADS = (
    json.loads(EXCLUSIONS_FILE.read_text(encoding='utf-8')).get('reanalysis_threads', [])
    if EXCLUSIONS_FILE.exists() else []
)
DV_ITEMS = {
    '지각된 유용성 (PU)': ['2-1.', '2-2.', '2-3.', '2-4.'],
    '사용 용이성 (PEU)': ['2-5.', '2-6.', '2-7.'],
    '전반적 만족도': ['3-1.', '3-2.', '3-3.'],
    '인지부하': ['3-4.', '3-5.', '3-6.'],
    '결과 신뢰도·품질': ['4-1.', '4-2.', '4-3.', '4-4.', '4-5.'],
    '상호작용 품질': ['4-6.', '4-7.', '4-8.'],
    '재사용 의도': ['5-1.'],
}
LITERACY_ITEMS = [f'6-{i}.' for i in range(1, 7)]
CONSTRUCT_ITEMS = {'AI 리터러시 (사전)': LITERACY_ITEMS, **DV_ITEMS}
GROUP_ORDER = ['A2UI · 초보자', 'A2UI · 숙련자', 'Baseline · 초보자', 'Baseline · 숙련자']
MODEL_FORMULA = 'score ~ C(UI, Sum) * C(숙련도, Sum)'
TERM_LABELS = {'C(UI, Sum)': 'UI', 'C(숙련도, Sum)': '숙련도', 'C(UI, Sum):C(숙련도, Sum)': 'UI × 숙련도'}


def load_survey():
    survey = pd.read_excel(SURVEY_FILE, sheet_name='병합 데이터')
    assert len(survey) == 40, '참가자 수가 40명이 아닙니다.'
    assert survey['참여자번호'].notna().all() and survey['참여자번호'].is_unique
    assert survey['인터페이스'].isin(['Agent2UI 방식', 'Baseline Prompt 방식']).all()
    return survey


def find_columns(survey, prefixes):
    result = []
    for prefix in prefixes:
        matches = [c for c in survey if str(c).strip().startswith(prefix)]
        if len(matches) != 1:
            raise ValueError(f'{prefix}: 일치하는 열 {len(matches)}개')
        result.append(matches[0])
    return result


def item_scores(survey, prefixes):
    values = survey[find_columns(survey, prefixes)].apply(pd.to_numeric, errors='coerce')
    if values.isna().any().any():
        raise ValueError(f'결측값 또는 숫자가 아닌 응답: {prefixes}')
    return values


def average_score(survey, prefixes):
    return item_scores(survey, prefixes).mean(axis=1)


def make_scores(survey):
    return pd.DataFrame({name: average_score(survey, items) for name, items in DV_ITEMS.items()})


def make_design(survey):
    literacy = average_score(survey, LITERACY_ITEMS)
    design = pd.DataFrame({
        'UI': np.where(survey['인터페이스'].str.contains('Agent2UI'), 'A2UI', 'Baseline'),
        'literacy_pre': literacy,
        '숙련도': np.where(literacy >= 6.0, '숙련자', '초보자'),
    }, index=survey.index)
    design['집단'] = design['UI'] + ' · ' + design['숙련도']
    return design


def significance_stars(p_value):
    if p_value < .05:
        return '**'
    if .05 < p_value < .1:
        return '*'
    return ''


def format_p(p_value):
    if pd.isna(p_value):
        return '—'
    return ('<.001' if p_value < .001 else f'{p_value:.3f}') + significance_stars(p_value)


def configure_plots():
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    fonts = {f.name for f in font_manager.fontManager.ttflist}
    font = next(f for f in ['AppleGothic', 'Arial Unicode MS', 'Malgun Gothic', 'DejaVu Sans'] if f in fonts)
    plt.rcParams.update({'font.family': font, 'axes.unicode_minus': False, 'font.size': 10,
                         'axes.titlesize': 12, 'axes.labelsize': 10, 'figure.dpi': 120})
    FIGURE_DIR.mkdir(exist_ok=True)
    return font


def fit_anova(design, values):
    data = design.copy()
    data['score'] = np.asarray(values, dtype=float)
    model = smf.ols(MODEL_FORMULA, data=data).fit()
    return model, data, anova_lm(model, typ=3)


def tidy_anova(variable, stage, model, table):
    return pd.DataFrame([{'종속변수': variable, '단계': stage, '효과': label,
                          'F': table.loc[term, 'F'], 'df1': int(table.loc[term, 'df']),
                          'df2': int(model.df_resid), 'p': table.loc[term, 'PR(>F)']}
                         for term, label in TERM_LABELS.items()])


def test_residual_assumptions(model, model_data):
    residuals = pd.Series(model.resid.to_numpy(), index=model_data.index)
    shapiro = stats.shapiro(residuals)
    levene = stats.levene(*[residuals.loc[model_data['집단'].eq(g)].to_numpy() for g in GROUP_ORDER], center='median')
    return {'Shapiro W': shapiro.statistic, '정규성 p': shapiro.pvalue,
            'Levene F': levene.statistic, '등분산성 p': levene.pvalue}


def survey_hash():
    return hashlib.sha256(SURVEY_FILE.read_bytes()).hexdigest()


def module_hash():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
