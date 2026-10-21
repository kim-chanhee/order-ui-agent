import { reviewState } from "../state.js?v=plan-sentence-redesign";
import { appState } from "../../state.js?v=plan-sentence-redesign";
import { clearElement, clone, createElement, getValueAtPath, setValueAtPath } from "../../utils.js?v=plan-sentence-redesign";
import { renderComponent } from "../../components/registry.js";
import { changedFieldNames, diffPlans } from "./plan-diff.js?v=plan-sentence-redesign";
import { isBlockVisible } from "./condition-evaluator.js?v=plan-sentence-redesign";
import { normalizeAnalysisPlan, normalizeUiPlan } from "./plan-normalizer.js?v=plan-sentence-redesign";
import { missingFieldsForPlan, validatePlanForConfirmation } from "./plan-validation.js?v=plan-sentence-redesign";
import { buildPlanSentence } from "./plan-sentence.js?v=plan-sentence-redesign";

export function prepareUiPlan(rawPlan) {
  const uiPlan = normalizeUiPlan(rawPlan || {});
  reviewState.currentSurface = null;
  reviewState.rawUiPlan = clone(uiPlan);
  reviewState.currentUiPlan = uiPlan;
  reviewState.currentPlan = normalizeAnalysisPlan(uiPlan.analysis_plan);
  reviewState.initialPlanSnapshot = clone(reviewState.currentPlan);
  return uiPlan;
}

export function renderPlanCard(container, uiPlan, handlers = {}) {
  if (uiPlan !== reviewState.currentUiPlan) reviewState.currentUiPlan = normalizeUiPlan(uiPlan || reviewState.currentUiPlan || {});
  if (reviewState.currentSurface?.surface_type === "plan") {
    reviewState.currentPlan = reviewState.currentSurface.data_model.analysis_plan;
    reviewState.currentUiPlan.analysis_plan = reviewState.currentPlan;
    reviewState.currentUiPlan.ui_state = reviewState.currentSurface.data_model.ui_state;
  } else {
    reviewState.currentPlan = normalizeAnalysisPlan(reviewState.currentUiPlan.analysis_plan);
  }
  // Field edits redraw the whole card from scratch, which would otherwise
  // recreate the <details> editor closed on every keystroke/click. Track the
  // user-toggled open state across redraws so editing a field doesn't slam the
  // panel shut under the user's cursor.
  let editorOpen = null;
  draw();

  function draw() {
    clearElement(container);
    const plan = reviewState.currentPlan;
    const blocks = reviewState.currentUiPlan.ui_blocks || [];
    const infeasible = reviewState.currentUiPlan.infeasible || [];
    const validation = validatePlanForConfirmation(plan, blocks, infeasible);
    reviewState.currentUiPlan.missing_fields = [...validation.missing_fields];
    const card = createElement("section", { className: "plan-card" });
    const head = createElement("header", { className: "plan-card-head" });
    head.append(
      createElement("h3", { text: "이렇게 분석할게요" }),
      createElement("p", { text: "검색 계획 한 문장을 확인하고 필요한 부분만 고치면 돼요." }),
    );
    card.append(head, renderPlanOverview(plan, infeasible));

    const context = componentContext(draw);

    // Core controls the LLM judged essential — always visible under the sentence.
    const primaryControls = createElement("div", { className: "plan-primary-controls plan-editor-dashboard" });
    const advancedBlocks = [];
    let primaryCount = 0;
    for (const rawBlock of blocks) {
      const block = blockForCurrentPlan(rawBlock, plan);
      if (block.type === "review") continue;
      if (!isBlockVisible(block, plan)) continue;
      if (isDegenerateNotice(block)) continue;
      if (block.section !== "primary") { advancedBlocks.push(block); continue; }
      const panel = createElement("section", { className: `plan-editor-panel${block.type === "date_range" ? " plan-editor-panel--period" : ""}` });
      panel.append(renderComponent(block, context));
      primaryControls.append(panel);
      primaryCount += 1;
    }
    if (primaryCount) card.append(primaryControls);

    const footer = createElement("div", { className: "plan-actions" });
    const statusGroup = createElement("div", { className: "plan-status-group" });
    statusGroup.append(createElement("p", {
      className: validation.valid ? "plan-status" : "plan-status invalid",
      text: validation.valid ? "실행 준비가 끝났어요." : validation.errors[0]?.message || "필수 조건을 확인해 주세요.",
    }));
    const buttons = createElement("div", { className: "plan-action-buttons" });
    const cancel = createElement("button", { className: "ghost", text: "취소", attrs: { type: "button" } });
    const confirm = createElement("button", { text: confirmButtonLabel(plan), attrs: { type: "button" } });
    confirm.disabled = !validation.valid || appState.isLoading;
    cancel.addEventListener("click", () => handlers.onCancel?.());
    confirm.addEventListener("click", () => handlers.onConfirm?.(buildConfirmPayload()));
    buttons.append(cancel, confirm); footer.append(statusGroup, buttons); card.append(footer);

    const editor = createElement("details", { className: "plan-editor" });
    const summary = createElement("summary"); const summaryText = createElement("span", { className: "plan-editor-summary" });
    summaryText.append(
      createElement("strong", { text: validation.valid ? "세부 조건 더보기" : "필수 조건 확인하기" }),
      createElement("small", { text: validation.valid ? "대상 이벤트, 결과 방식, 비교 기준 등을 바꿀 수 있어요." : "표시된 항목을 확인해야 실행할 수 있어요." }),
    );
    summary.append(summaryText); editor.append(summary);
    editor.append(renderAdvancedBody(advancedBlocks, context, handlers, draw));
    card.append(editor);
    editor.open = editorOpen === null ? !validation.valid : editorOpen;
    editor.addEventListener("toggle", () => { editorOpen = editor.open; });

    for (const warning of userFacingWarnings(reviewState.currentUiPlan)) card.append(createElement("p", { className: "plan-warning", text: warning }));
    container.append(card);
  }
}

function componentContext(redraw) {
  return {
    plan: reviewState.currentPlan,
    pathFor: (block) => block.field_path || block.field || block.key,
    valueFor: (block) => getValueAtPath(reviewState.currentPlan, block.field_path || block.field || block.key),
    update: (path, value) => {
      setValueAtPath(reviewState.currentPlan, path, value);
      if (path === "date_range" && ["relative", "preset"].includes(value?.mode)) reviewState.currentPlan.date_anchor = { strategy: "dataset_max" };
      if (path === "date_range" && ["all_time", "custom"].includes(value?.mode)) reviewState.currentPlan.date_anchor = null;
      // Toggling a nested metric field off must not leave an invalid stub object
      // (e.g. {kind: null}) that fails AnalysisPlan validation on confirm.
      if (path === "metric.kind" && !value) reviewState.currentPlan.metric = null;
      // output.view has no null state in the schema; clearing it reverts to the default.
      if (path === "output.view" && !value) {
        reviewState.currentPlan.output = { ...(reviewState.currentPlan.output || {}), view: "table" };
      }
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

function renderAdvancedBody(blocks, context, handlers, redraw) {
  const suggestions = reviewState.currentUiPlan.suggested_constraints || [];
  const uiState = reviewState.currentUiPlan.ui_state ||= {};
  let selectedSuggestionId = uiState.selected_suggestion_id || null;
  const appliedConstraints = Array.isArray(uiState.additional_constraints) ? uiState.additional_constraints : [];
  const body = createElement("div", { className: "plan-grid-advanced" });
  for (const block of blocks) if (isBlockVisible(block, reviewState.currentPlan)) body.append(renderComponent(block, context));
  if (suggestions.length) {
    const suggestionBox = createElement("section", { className: "plan-suggestions" });
    suggestionBox.append(
      createElement("strong", { text: "다음으로 이런 조건을 확인해 보세요" }),
      createElement("small", { text: "현재 분석을 바탕으로 예상했습니다. 선택한 뒤 자유롭게 고칠 수 있어요." }),
    );
    const chips = createElement("div", { className: "plan-choice-chips" });
    for (const suggestion of suggestions) {
      const button = createElement("button", { className: "ghost", text: suggestion.label, attrs: { type: "button", title: suggestion.reason || "" } });
      button.addEventListener("click", () => {
        input.value = suggestion.text;
        selectedSuggestionId = suggestion.id;
        uiState.selected_suggestion_id = suggestion.id;
        sync();
        input.focus?.();
      });
      chips.append(button);
    }
    suggestionBox.append(chips); body.append(suggestionBox);
  }
  if (appliedConstraints.length) {
    const applied = createElement("section", { className: "plan-applied-constraints" });
    applied.append(createElement("strong", { text: "적용된 조건" }));
    const list = createElement("div", { className: "plan-applied-list" });
    for (const constraint of appliedConstraints) list.append(createElement("span", { text: constraint }));
    applied.append(list); body.append(applied);
  }
  const free = createElement("section", { className: "plan-additional-condition plan-field-full" });
  free.append(
    createElement("strong", { text: "추가 조건" }),
    createElement("small", { text: "입력한 문장을 분석 가능한 필터로 바꾼 뒤 계획에 반영합니다." }),
  );
  const inputRow = createElement("div", { className: "plan-additional-input" });
  const input = createElement("input", { attrs: {
    type: "text",
    maxlength: 2000,
    placeholder: "예: 테스트 주문 제외, 특정 고객만, 최소 주문 5건 이상",
    "aria-label": "추가 조건",
  } });
  input.value = uiState.additional_constraint || "";
  const apply = createElement("button", { className: "ghost", text: "조건 적용", attrs: { type: "button" } });
  const sync = () => {
    const value = input.value.trim();
    uiState.additional_constraint = input.value;
    apply.disabled = !value || appliedConstraints.some((item) => item.trim().toLocaleLowerCase() === value.toLocaleLowerCase());
  };
  const submit = () => {
    const value = input.value.trim();
    if (!value || apply.disabled) return;
    apply.disabled = true;
    handlers.onRefine?.(value, selectedSuggestionId);
  };
  input.addEventListener("input", () => { selectedSuggestionId = null; uiState.selected_suggestion_id = null; sync(); });
  input.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.isComposing) return;
    event.preventDefault();
    submit();
  });
  apply.addEventListener("click", submit);
  sync();
  inputRow.append(input, apply); free.append(inputRow); body.append(free); return body;
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

export function planMeaning(plan = {}) { return { question: plan.original_question || "", meaning: summaryItems(plan).map((item) => `${item.key}: ${item.value}`).join(", ") }; }
export function userFacingWarnings(uiPlan = {}) {
  return [...new Set((uiPlan.warnings || []).map(String).filter((item) => (
    item
    && !/structured|fallback|LLM planner|not configured/i.test(item)
    && !/고유.*수로 집계|총건수.*고유 주문/.test(item)
  )))];
}
export function blockForCurrentPlan(block) { return block; }
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
  if (plan.metric) items.push({ key: "지표", value: [plan.metric, ...(plan.metrics || [])].map(metricSummary).filter((value, index, all) => all.indexOf(value) === index).join(" · ") });
  if (Array.isArray(plan.group_by)) items.push({ key: "집계", value: plan.group_by.length ? plan.group_by.map(dimensionLabel).join(", ") : "전체" });
  if ((plan.filters || []).length) items.push({ key: "추가 조건", value: `${plan.filters.length}개` });
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
  const basis = calculationSummary(plan);
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
function semanticLabel(value) {
  return ({ "failed delivery": "배송 실패", "package delivered": "배송 완료" })[String(value).toLowerCase()] || String(value);
}
// The planner fills `metric.unit` with a raw schema token (often the English
// table/column name, e.g. "orders"). Translate the common ones so summary
// chips don't mix Korean and English mid-sentence; unknown tokens fall back
// to the raw value as before.
const UNIT_LABELS = {
  order: "주문", orders: "주문", order_id: "주문",
  customer: "고객", customers: "고객", customer_id: "고객",
  item: "물품", items: "물품", item_id: "물품",
  product: "상품", products: "상품", product_id: "상품",
  package: "패키지", packages: "패키지", package_id: "패키지",
  courier: "배송 기사", couriers: "배송 기사", courier_id: "배송 기사",
  shipper: "배송 기사", shippers: "배송 기사", shipper_id: "배송 기사",
  event: "이벤트", events: "이벤트", event_id: "이벤트",
  employee: "직원", employees: "직원", employee_id: "직원",
};
function unitLabel(unit) {
  if (!unit) return "항목";
  return UNIT_LABELS[String(unit).trim().toLowerCase()] || String(unit);
}
// Mirrors _DIMENSION_LABELS in app/planning/option_catalog.py so the summary
// chip reads the same as the "집계 기준" checkboxes in the editor below it.
const DIMENSION_LABELS = {
  customer_id: "고객별", courier_id: "배송 기사별", shipper_id: "배송 기사별",
  employee_id: "직원별", product_id: "상품별", item_id: "물품별",
  order_id: "주문별", package_id: "패키지별", event_id: "이벤트별",
  event_type: "이벤트 유형별", status: "상태별", day: "일자별",
};
function dimensionLabel(value) {
  return DIMENSION_LABELS[String(value).trim().toLowerCase()] || `${value}별`;
}
function metricSummary(metric = {}) { if (metric.kind === "count") return `${metric.distinct ? "고유 " : ""}${unitLabel(metric.unit)} 수`; if (metric.kind === "ratio") return "비율"; return ({ rows: "상세 목록", sum: "합계", avg: "평균", min: "최솟값", max: "최댓값" })[metric.kind] || "선택 필요"; }
export function calculationSummary(plan = {}) {
  const metric = plan.metric || {};
  if (metric.kind === "count") return `${metric.distinct ? "중복을 제거한 " : ""}${unitLabel(metric.unit)} 기준`;
  if (metric.kind === "ratio") return "선택한 두 기준의 비율";
  if (metric.kind === "rows") return "조건에 맞는 상세 행 기준";
  return metric.unit ? `${unitLabel(metric.unit)} 기준` : "";
}
function dateSummary(value, anchor = {}) {
  if (!value) return { primary: "선택 필요" };
  if (value.mode === "all_time") return { primary: "전체 기간" };
  if (value.mode === "custom") return { primary: `${value.date_from || "?"} ~ ${value.date_to || "?"}` };
  const detail = anchor?.resolved_date_from && anchor?.resolved_date_to ? `${anchor.resolved_date_from} ~ ${anchor.resolved_date_to}` : "";
  if (value.mode === "relative") return { primary: `최근 ${value.relative_days || "?"}일`, detail };
  const presetLabel = ({ last_7_days: "최근 7일", last_14_days: "최근 14일", last_30_days: "최근 30일", last_60_days: "최근 60일", last_90_days: "최근 90일" })[value.preset] || "선택 필요";
  return { primary: presetLabel, detail };
}
function confirmButtonLabel(plan) { if (plan.metric?.kind === "count") return "이 조건으로 건수 확인"; if (plan.metric?.kind === "ratio") return "이 기준으로 비교 실행"; if (plan.metric?.kind === "rows") return "이 조건으로 목록 확인"; return "이 조건으로 실행"; }
