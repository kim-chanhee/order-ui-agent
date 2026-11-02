import { reviewState } from "../state.js?v=dynamic-blueprint-v1";
import { appState } from "../../state.js?v=dynamic-blueprint-v1";
import { clearElement, clone, createElement, getValueAtPath, setValueAtPath } from "../../utils.js?v=dynamic-blueprint-v1";
import { renderComponent } from "../../components/registry.js";
import { changedFieldNames, diffPlans } from "./plan-diff.js?v=dynamic-blueprint-v1";
import { isBlockVisible } from "./condition-evaluator.js?v=dynamic-blueprint-v1";
import { normalizeAnalysisPlan, normalizeUiPlan } from "./plan-normalizer.js?v=dynamic-blueprint-v1";
import { missingFieldsForPlan, validatePlanForConfirmation } from "./plan-validation.js?v=dynamic-blueprint-v1";
import { unitLabel, dimensionLabel, semanticLabel, metricNounPhrase, presetLabel } from "./plan-labels.js?v=dynamic-blueprint-v1";
import { buildPlanSentence } from "./plan-sentence.js?v=dynamic-blueprint-v1";

const CORE_CARDS = [
  { key: "metric", title: "결과 지표", hint: "무엇을 계산할지 확인하세요" },
  { key: "group_by", title: "집계 기준", hint: "결과를 나누어 보여줄 단위" },
  { key: "date_range", title: "분석 기간", hint: "최근 기간은 데이터 최신일 기준" },
  { key: "event_types", title: "대상 이벤트", hint: "분석에 포함할 업무 이벤트" },
];

export function cardKeyForBlock(block) {
  const path = block.field_path || block.field || block.key || "";
  if (/^metrics?(\.|\[|$)/.test(path)) return "metric";
  return CORE_CARDS.find(({ key }) => path === key || path.startsWith(key + ".") || path.startsWith(key + "["))?.key || null;
}

export function renderPlanCard(container, uiPlan, handlers = {}) {
  reviewState.currentUiPlan = normalizeUiPlan(uiPlan);
  reviewState.currentPlan = reviewState.currentSurface?.data_model.analysis_plan || reviewState.currentUiPlan.analysis_plan;
  let activeEditor = null;
  let editorOpen = false;
  let busy = false;
  let feedback = "";
  let failed = false;
  const editorId = `plan-editor-${reviewState.currentUiPlan.surface_id || "legacy"}`;
  const dirty = () => diffPlans(reviewState.savedPlanSnapshot || reviewState.initialPlanSnapshot, reviewState.currentPlan).length > 0;

  async function save() {
    if (!dirty()) return true;
    if (!handlers.onSave) throw new Error("계획 저장 연결이 없습니다. 새 분석 계획을 요청해 주세요.");
    await handlers.onSave(buildConfirmPayload());
    return true;
  }

  async function perform(action) {
    if (busy || appState.isLoading) return;
    busy = true; feedback = "변경한 조건을 확인하고 있습니다…"; failed = false; draw();
    try { await action(); }
    catch (error) { failed = true; feedback = error.message || "조건을 저장하지 못했습니다. 다시 시도해 주세요."; }
    finally { busy = false; if (!container.classList.contains("confirmed")) draw(); }
  }

  function renderBlock(block, context) {
    block = optionsForBlock(block, reviewState.currentPlan, reviewState.currentUiPlan.ui_state?.semantic_catalog);
    const panel = createElement("section", { className: "plan-editor-panel" });
    panel.append(renderComponent(block, context));
    panel.querySelectorAll("input, select, textarea").forEach((input, index) => { input.dataset.focusKey = `${block.key}-${index}`; });
    return panel;
  }

  function draw() {
    const focused = container.contains(document.activeElement) ? document.activeElement : null;
    const focusKey = focused?.dataset.focusKey;
    const selection = focused && ["text", "textarea"].includes(focused.type) ? [focused.selectionStart, focused.selectionEnd] : null;
    clearElement(container);
    const plan = reviewState.currentPlan;
    const blocks = (reviewState.currentUiPlan.ui_blocks || []).filter((b) => b.type !== "review" && !isDegenerateNotice(b) && isBlockVisible(b, plan));
    const infeasible = reviewState.currentUiPlan.infeasible || [];
    const validation = validatePlanForConfirmation(plan, reviewState.currentUiPlan.ui_blocks, infeasible, reviewState.currentUiPlan.ui_state?.semantic_catalog);
    reviewState.currentUiPlan.missing_fields = [...validation.missing_fields];
    const card = createElement("section", { className: "plan-card plan-card-v2", attrs: { "aria-label": "분석 계획 확인", "aria-busy": String(busy) } });
    const head = createElement("header", { className: "plan-card-head" });
    const heading = createElement("div", { className: "plan-heading-row" });
    heading.append(createElement("h3", { text: "분석 계획 확인" }), createElement("span", { className: "plan-recommendation", text: "AI 추천 계획" }));
    head.append(heading, createElement("p", { text: "AI가 제안한 조건을 확인하고, 필요한 항목만 수정하세요." }));
    const question = createElement("div", { className: "plan-original-question" });
    question.append(createElement("small", { text: "내 질문" }), createElement("strong", { text: plan.original_question }));
    head.append(question);
    if (reviewState.currentUiPlan.summary && !diffPlans(reviewState.initialPlanSnapshot,plan).length) head.append(createElement("p", { className: "plan-purpose", text: reviewState.currentUiPlan.summary }));
    head.append(renderPlanOverview(plan, infeasible));
    card.append(head);
    const body = createElement("div", { className: "plan-content" });
    const title = createElement("div", { className: "plan-heading-row" });
    const reset = createElement("button", { className: "ghost plan-reset", text: "추천 조건으로 되돌리기", attrs: { type: "button" } });
    reset.disabled = !diffPlans(reviewState.initialPlanSnapshot, plan).length;
    reset.addEventListener("click", () => perform(async () => {
      reviewState.currentPlan = clone(reviewState.initialPlanSnapshot);
      syncPlanState();
      await save(); activeEditor = null; feedback = "추천 조건으로 되돌렸습니다.";
    }));
    title.append(createElement("h4", { text: "분석 조건" }), reset); body.append(title);
    const context = componentContext(() => { feedback = ""; failed = false; draw(); });
    const grid = createElement("div", { className: "plan-condition-grid" });
    const summary = summaryItems(plan);
    const primary = blocks.filter((b) => b.section !== "advanced");
    const advancedBlocks = blocks.filter((b) => b.section === "advanced");
    const appendCard = (block, target) => {
      const path = block.field_path || block.key;
      if (!block.field_path || ["notice"].includes(block.type)) { target.append(renderBlock(block, context)); return; }
      const button = createElement("button", { className: `plan-condition-card${activeEditor === block.key ? " active" : ""}`, attrs: {
        type: "button", "aria-expanded": String(activeEditor === block.key), "aria-controls": editorId,
      } });
      button.dataset.focusKey = `card-${block.key}`;
      const label = createElement("span", { className: "plan-condition-label", text: block.label });
      if (JSON.stringify(getValueAtPath(plan,path)) !== JSON.stringify(getValueAtPath(reviewState.initialPlanSnapshot,path))) label.append(createElement("span", { className: "plan-change-badge", text: "변경됨" }));
      button.append(label, createElement("strong", { text: blockValueLabel(block, plan) }), createElement("small", { text: block.description || "조건 수정" }));
      button.addEventListener("click", () => { activeEditor = activeEditor === block.key ? null : block.key; draw(); });
      target.append(button);
      if (activeEditor === block.key) {
        const panel = createElement("section", { className: "plan-card-editor", attrs: { id: editorId, "aria-label": "조건 편집" } });
        const row = createElement("div", { className: "plan-heading-row" });
        const close = createElement("button", { className: "ghost", text: "닫기", attrs: { type: "button" } });
        close.dataset.focusKey = `card-${block.key}`;
        close.addEventListener("click", () => { activeEditor = null; draw(); });
        row.append(createElement("strong", { text: `${block.label} 변경` }), close); panel.append(row, renderBlock(block,context));
        target.append(panel);
      }
    };
    for (const block of primary) appendCard(block,grid);
    body.append(grid);
    if (advancedBlocks.length) {
      const advanced = createElement("details", { className: "plan-editor" });
      advanced.open = editorOpen;
      advanced.append(createElement("summary", { text: "세부 조건 더보기" }));
      const advancedGrid = createElement("div", { className: "plan-condition-grid" });
      for (const block of advancedBlocks) appendCard(block,advancedGrid);
      advanced.append(advancedGrid);
      advanced.addEventListener("toggle", () => { editorOpen = advanced.open; });
      body.append(advanced);
    }
    const preview = createElement("section", { className: "plan-preview" });
    preview.append(createElement("h4", { text: "이 조건으로 분석합니다" }), renderPlanOverview(plan));
    const facts = createElement("dl", { className: "plan-preview-facts" });
    for (const item of summary) facts.append(createElement("dt", { text: item.key }), createElement("dd", { text: item.value + (item.detail ? ` · ${item.detail}` : "") }));
    if (plan.limit) facts.append(createElement("dt", { text: "최대 결과 수" }), createElement("dd", { text: `${plan.limit}개` }));
    preview.append(facts); body.append(preview);
    if (!validation.valid) {
      const errors = createElement("div", { className: "plan-validation-errors", attrs: { role: "status" } });
      for (const error of validation.errors) errors.append(createElement("p", { text: error.message }));
      body.append(errors);
    }
    for (const warning of userFacingWarnings(reviewState.currentUiPlan)) body.append(createElement("p", { className: "plan-warning", text: warning }));
    card.append(body);
    const footer = createElement("div", { className: "plan-actions" });
    footer.append(createElement("p", { className: `plan-status${failed ? " invalid" : ""}`, text: feedback || (dirty() ? "변경한 조건을 저장해 주세요." : "조건을 확인한 후 분석을 실행하세요."), attrs: { role: "status", "aria-live": "polite" } }));
    const buttons = createElement("div", { className: "plan-action-buttons" });
    const cancel = createElement("button", { className: "ghost", text: "취소", attrs: { type: "button" } });
    cancel.addEventListener("click", () => handlers.onCancel?.());
    const apply = createElement("button", { className: "ghost", text: "변경 저장", attrs: { type: "button" } });
    apply.disabled = !dirty();
    apply.addEventListener("click", () => perform(async () => { await save(); feedback = "변경한 조건을 저장했습니다."; }));
    const confirm = createElement("button", { text: "이 계획으로 분석 실행 →", attrs: { type: "button" } });
    confirm.disabled = !validation.valid || !handlers.onConfirm;
    confirm.addEventListener("click", () => perform(async () => { await save(); await handlers.onConfirm(buildConfirmPayload()); feedback = ""; }));
    buttons.append(cancel, apply, confirm); footer.append(buttons); card.append(footer); container.append(card);
    if (busy) card.querySelectorAll("button, input, select, textarea").forEach((node) => { node.disabled = true; });
    if (focusKey && !busy) {
      const next = [...card.querySelectorAll("[data-focus-key]")].find((node) => node.dataset.focusKey === focusKey);
      next?.focus({ preventScroll: true });
      if (selection && next?.setSelectionRange) next.setSelectionRange(...selection);
    }
  }
  draw();
}

function syncPlanState() {
  reviewState.currentUiPlan.analysis_plan = reviewState.currentPlan;
  if (reviewState.currentSurface) reviewState.currentSurface.data_model.analysis_plan = reviewState.currentPlan;
}

function componentContext(redraw) {
  return {
    plan: reviewState.currentPlan,
    pathFor: (block) => block.field_path || block.field || block.key,
    valueFor: (block) => getValueAtPath(reviewState.currentPlan, block.field_path || block.field || block.key),
    update: (path, value) => {
      applyLocalPlanEdit(reviewState.currentPlan, path, value, reviewState.currentUiPlan.ui_state?.semantic_catalog);
      markUserModified(path);
      reviewState.currentUiPlan.analysis_plan = reviewState.currentPlan;
      reviewState.currentUiPlan.missing_fields = missingFieldsForPlan(reviewState.currentPlan, reviewState.currentUiPlan.ui_blocks || []);
      if (reviewState.currentSurface?.surface_type === "plan") {
        reviewState.currentSurface.data_model.analysis_plan = reviewState.currentPlan;
        reviewState.currentSurface.data_model.field_metadata = reviewState.currentPlan.field_metadata || {};
        reviewState.currentSurface.data_model.missing_fields = [...reviewState.currentUiPlan.missing_fields];
      }
      redraw();
    },
  };
}

export function blockValueLabel(block, plan) {
  const path = block.field_path || block.key;
  const value = getValueAtPath(plan,path);
  if (path === "date_range") return dateSummary(value,plan.date_anchor).primary;
  if (path === "metric.kind" || path === "metric") return metricNounPhrase(plan.metric || {});
  if (value == null || value === "" || (Array.isArray(value) && !value.length)) return "선택 필요";
  const label = (v) => block.options?.find((o) => o.value === String(v))?.label || String(v);
  if (Array.isArray(value)) return value.map((v) => typeof v === "object" ? `${v.field || ""} ${v.direction === "asc" ? "오름차순" : "내림차순"}` : label(v)).join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return label(value);
}

export function optionsForBlock(block, plan, catalog) {
  if (!catalog) return block;
  const path = block.field_path || block.key;
  let options;
  if (path === "metric.field") options = plan.metric?.kind === "count" ? catalog.count_fields : catalog.numeric_fields;
  if (path === "group_by") {
    const definition = catalog.semantic_metrics?.[plan.metric?.semantic_id];
    options = definition ? catalog.group_by.filter((o) => definition.group_by.includes(o.value)) : catalog.group_by;
  }
  if (path === "metric.semantic_id") options = Object.entries(catalog.semantic_metrics || {})
    .filter(([,d]) => (d.kind || "ratio") === plan.metric?.kind)
    .map(([value,d]) => ({value,label:d.label}));
  return options ? {...block,options} : block;
}

export function applyLocalPlanEdit(plan, path, value, catalog = {}) {
  const previous = clone(plan.metric);
  setValueAtPath(plan,path,value);
  if (path === "date_range") plan.date_anchor = ["relative","preset"].includes(value?.mode) ? {strategy:"dataset_max"} : null;
  if (path.startsWith("metric.") && plan.metric) {
    const m = plan.metric;
    const kindChanged = previous?.kind !== m.kind;
    if (m.kind === "ratio") {
      const entries = Object.entries(catalog?.semantic_metrics || {}).filter(([,d]) => (d.kind || "ratio") === "ratio");
      const selected = entries.find(([id]) => id === m.semantic_id) || (kindChanged && entries.length === 1 ? entries[0] : null);
      if (selected) {
        const [id,d] = selected;
        if (kindChanged && JSON.stringify(plan.event_types || []) === JSON.stringify([d.numerator_event])) plan.event_types = [...d.population_events];
        Object.assign(m,{semantic_id:id,field:d.field,numerator:d.numerator,denominator:d.denominator,unit:d.label,distinct:true});
      }
    } else if (m.kind === "count") {
      if (kindChanged) Object.assign(m,{semantic_id:null,numerator:null,denominator:null});
      const units = {order_id:"order",customer_id:"customer",courier_id:"courier",product_id:"product",item_id:"item",event_id:"event",employee_id:"employee",package_id:"package"};
      if (units[m.field]) m.unit = units[m.field];
      m.distinct = true;
    } else if (kindChanged) {
      Object.assign(m,{semantic_id:null,numerator:null,denominator:null,distinct:null});
      if (m.kind === "rows" || !(catalog?.numeric_fields || []).some((o) => o.value === m.field)) Object.assign(m,{field:null,unit:null});
    }
    if (path === "metric.kind" && !value) plan.metric = null;
    plan.metrics = (plan.metrics || []).map((metric) => JSON.stringify(metric) === JSON.stringify(previous) ? clone(plan.metric) : metric).filter(Boolean);
  }
  if (path === "output.view" && !value) plan.output.view = "table";
  return plan;
}

function markUserModified(path) {
  const root = String(path).split(".")[0];
  reviewState.currentPlan.field_metadata ||= {};
  const previous = reviewState.currentPlan.field_metadata[path] || reviewState.currentPlan.field_metadata[root] || {};
  reviewState.currentPlan.field_metadata[root] = { ...previous, status: "user_modified", confidence: 1, source: "user_selected" };
}

export function buildConfirmPayload(diff = diffPlans(reviewState.initialPlanSnapshot, reviewState.currentPlan)) {
  const analysisPlan = normalizeAnalysisPlan(reviewState.currentPlan);
  const currentUiPlan = reviewState.currentUiPlan || {};
  const uiState = currentUiPlan.ui_state || {};
  const surface = {
    surface_id: currentUiPlan.surface_id || reviewState.currentSurface?.surface_id || null,
    plan_id: currentUiPlan.plan_id || reviewState.currentSurface?.plan_id || null,
    revision: currentUiPlan.revision || reviewState.currentSurface?.revision || null,
    selected_suggestion_id: uiState.selected_suggestion_id ?? currentUiPlan.selected_suggestion_id ?? null,
    refinement_count: Number(uiState.refinement_count ?? currentUiPlan.refinement_count ?? 0),
  };
  const uiPlan = buildUiPlanRequest(currentUiPlan, analysisPlan);
  return {
    uiPlan, analysisPlan,
    surface,
    clientMetrics: { changed_fields: changedFieldNames(diff), plan_diff: diff, plan_changed: diff.length > 0 },
  };
}

export function buildUiPlanRequest(sourceUiPlan, analysisPlan) {
  const uiPlan = clone(sourceUiPlan || {});
  delete uiPlan.surface_id;
  delete uiPlan.plan_id;
  delete uiPlan.revision;
  delete uiPlan.selected_suggestion_id;
  delete uiPlan.refinement_count;
  uiPlan.ui_blocks = (uiPlan.ui_blocks || []).map(serverUiBlock);
  uiPlan.analysis_plan = analysisPlan;
  uiPlan.missing_fields = missingFieldsForPlan(analysisPlan, uiPlan.ui_blocks || []);
  return uiPlan;
}

function serverUiBlock(block = {}) {
  return {
    type: block.type,
    key: block.key,
    field_path: block.field_path ?? block.field ?? null,
    label: block.label ?? "",
    description: block.description || null,
    required: Boolean(block.required),
    required_if: block.required_if || null,
    visible_if: block.visible_if || null,
    options: Array.isArray(block.options) ? clone(block.options) : [],
    props: block.props || {},
    section: block.section || "primary",
  };
}

export function userFacingWarnings(uiPlan = {}) {
  return [...new Set((uiPlan.warnings || []).map(String).filter((item) => (
    item
    && !/structured|fallback|LLM planner|not configured/i.test(item)
    && !/고유.*수로 집계|총건수.*고유 주문/.test(item)
  )))];
}
// The planner occasionally emits a placeholder "notice" block whose text is
// just the literal component-type fallback ("review") instead of real
// copy. It carries no information for the user, so skip rendering it.
function isDegenerateNotice(block) {
  if (block.type !== "notice") return false;
  const text = String(block.description || block.label || "").trim().toLowerCase();
  return text === "review" || text === "";
}

export function summaryItems(plan = {}) {
  const items = [];
  if (plan.date_range || plan.field_metadata?.date_range) {
    const { primary, detail } = dateSummary(plan.date_range, plan.date_anchor);
    items.push({ key: "기간", value: primary, detail });
  }
  if ((plan.event_types || []).length || (plan.target_conditions || []).length) items.push({ key: "대상", value: [...(plan.event_types || []), ...(plan.target_conditions || [])].map(semanticLabel).join(", ") || "선택 필요" });
  const metrics = [plan.metric, ...(plan.metrics || [])].filter(Boolean);
  if (metrics.length) items.push({ key: "지표", value: metrics.map(metricNounPhrase).filter((value, index, all) => all.indexOf(value) === index).join(" · ") });
  if (Array.isArray(plan.group_by)) items.push({ key: "집계", value: plan.group_by.length ? plan.group_by.map(dimensionLabel).join(", ") : "전체" });
  if (plan.comparison) items.push({key:"비교",value:{event_vs_event:"이벤트 간 비교",breakdown:"항목별 분포",none:"비교 없음"}[plan.comparison] || plan.comparison});
  if (plan.sort?.length) items.push({key:"정렬",value:plan.sort.map((s) => `${s.field === "metric" ? "결과 지표" : s.field} ${s.direction === "asc" ? "오름차순" : "내림차순"}`).join(", ")});
  if (plan.output?.view) items.push({key:"결과 표시",value:{summary:"요약",table:"표",chart:"차트",table_and_chart:"표와 차트"}[plan.output.view] || plan.output.view});
  if ((plan.filters || []).length) items.push({ key: "추가 조건", value: plan.filters.map((f) => `${plan.field_metadata?.[f.field]?.label || f.field} ${f.operator} ${Array.isArray(f.value) ? f.value.join(", ") : f.value}`).join(" · ") });
  return items;
}
function renderPlanOverview(plan, infeasibleList = []) {
  const node = createElement("section", { className: "plan-overview" });
  const infeasibleFields = new Set(infeasibleList.map((item) => item.field_path).filter(Boolean));
  const sentence = createElement("p", { className: "plan-sentence" });
  const segments = buildPlanSentence(plan, { infeasibleFields });
  segments.forEach((segment, index) => {
    if (segment.blocked) sentence.append(createElement("span", { className: "plan-sentence-blocked", text: segment.text }));
    else if (segment.missing) sentence.append(createElement("span", { className: "plan-sentence-missing", text: segment.text }));
    else sentence.append(document.createTextNode(segment.text));
    if (index < segments.length - 1) sentence.append(document.createTextNode(" "));
  });
  node.append(sentence);
  const basis = calculationSummary(plan, reviewState.currentUiPlan?.ui_state?.semantic_catalog);
  if (basis) {
    const calculation = createElement("p", { className: "plan-calculation" });
    calculation.append(createElement("small", { text: "계산 기준" }), createElement("span", { text: basis }));
    node.append(calculation);
  }
  if (infeasibleList.length) {
    const box = createElement("section", { className: "plan-infeasible-reasons" });
    box.append(createElement("strong", { text: "현재 데이터로 검색할 수 없는 조건이 있어요" }));
    const list = createElement("ul");
    for (const item of infeasibleList) list.append(createElement("li", { text: item.reason || item.label }));
    box.append(list);
    node.append(box);
  }
  return node;
}
export function calculationSummary(plan = {}, catalog = null) {
  const metric = plan.metric || {};
  if (metric.kind === "count") return `${metric.distinct ? "중복을 제거한 " : ""}${unitLabel(metric.unit)} 기준`;
  if (metric.kind === "ratio") return catalog?.semantic_metrics?.[metric.semantic_id]?.description || "검증된 분자와 분모의 비율";
  if (metric.kind === "rows") return "조건에 맞는 상세 행 기준";
  return metric.unit ? `${unitLabel(metric.unit)} 기준` : "";
}
function dateSummary(value, anchor = {}) {
  if (!value) return { primary: "선택 필요" };
  if (value.mode === "all_time") return { primary: "전체 기간" };
  if (value.mode === "custom") return { primary: `${value.date_from || "?"} ~ ${value.date_to || "?"}` };
  const detail = anchor?.resolved_date_from && anchor?.resolved_date_to ? `${anchor.resolved_date_from} ~ ${anchor.resolved_date_to}` : "";
  if (value.mode === "relative") return { primary: `최근 ${value.relative_days || "?"}일`, detail };
  return { primary: presetLabel(value.preset), detail };
}
