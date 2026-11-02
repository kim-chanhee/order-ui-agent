import { getValueAtPath } from "../../utils.js?v=dynamic-blueprint-v1";
import { isBlockRequired, isBlockVisible } from "./condition-evaluator.js?v=dynamic-blueprint-v1";

export function validatePlanForConfirmation(plan, uiBlocks = [], infeasible = [], catalog = null) {
  const errors = [];
  if (!plan) return { valid: false, errors: [{ field: "plan", message: "실행할 계획이 없습니다." }], missing_fields: ["plan"] };
  if (!String(plan.original_question || "").trim()) errors.push({ field: "original_question", message: "실행할 질문이 없습니다." });
  const missingFields = missingFieldsForPlan(plan, uiBlocks);
  for (const field of missingFields) {
    const block = uiBlocks.find((item) => (item.field_path || item.key) === field);
    errors.push({ field, message: `${block?.label || field}을(를) 확인해야 합니다.` });
  }
  for (const item of infeasible || []) {
    errors.push({ field: "infeasible", message: item?.reason || item?.label || "현재 데이터로 검색할 수 없는 조건이 있습니다." });
  }
  for (const message of plan.unresolved_constraints || []) errors.push({ field: "unresolved_constraints", message: String(message) });
  if (plan.date_range?.mode === "custom" && plan.date_range.date_from && plan.date_range.date_to && plan.date_range.date_from > plan.date_range.date_to) {
    errors.push({ field: "date_range", message: "시작일은 종료일보다 늦을 수 없습니다." });
  }
  for (const metric of [plan.metric, ...(plan.metrics || [])]) {
    if (metric?.kind === "ratio" && (!metric.numerator || !metric.denominator)) errors.push({ field: "metric", message: "비율의 분자와 분모를 확인해야 합니다." });
  }
  if (plan.comparison === "event_vs_event" && (plan.event_types || []).length < 2) errors.push({ field: "event_types", message: "이벤트 비교에는 두 개 이상의 이벤트가 필요합니다." });
  if (plan.date_range?.mode === "custom" && (!plan.date_range.date_from || !plan.date_range.date_to)) errors.push({ field: "date_range", message: "시작일과 종료일을 모두 입력해 주세요." });
  if (plan.date_range?.mode === "relative" && (!Number.isInteger(plan.date_range.relative_days) || plan.date_range.relative_days < 1 || plan.date_range.relative_days > 3650)) errors.push({ field: "date_range", message: "기간은 1~3650일의 정수로 입력해 주세요." });
  if (catalog) {
    const definitions = catalog.semantic_metrics || {};
    const numeric = new Set((catalog.numeric_fields || []).map((o) => o.value));
    const groups = new Set((catalog.group_by || []).map((o) => o.value));
    if ((plan.group_by || []).some((g) => !groups.has(g))) errors.push({field:"group_by",message:"스키마에서 지원하지 않는 집계 기준입니다."});
    for (const m of [plan.metric,...(plan.metrics || [])].filter(Boolean)) {
      if (["sum","avg","min","max"].includes(m.kind) && !numeric.has(m.field)) errors.push({field:"metric.field",message:"유효한 수치 집계 필드를 선택해 주세요."});
      if (m.kind === "count" && !m.field) errors.push({field:"metric.field",message:"중복 제거 기준을 선택해 주세요."});
      if (m.kind === "ratio") {
        const d = definitions[m.semantic_id];
        if (!d || m.numerator !== d.numerator || m.denominator !== d.denominator) errors.push({field:"metric",message:"검증된 비율 정의를 선택해 주세요."});
        else if ((plan.group_by || []).some((g) => !d.group_by.includes(g))) errors.push({field:"group_by",message:"이 비율에서 지원하지 않는 집계 기준입니다."});
      }
    }
  }
  return { valid: errors.length === 0, errors, missing_fields: missingFields };
}

export function missingFieldsForPlan(plan, uiBlocks = []) {
  const missing = [];
  for (const block of uiBlocks) {
    if (!isBlockVisible(block, plan) || !isBlockRequired(block, plan)) continue;
    // 안내 전용 블록은 서버 검증과 동일하게 필수 입력 검사에서 제외한다.
    if (block.field_path == null && ["review", "notice"].includes(block.type)) continue;
    const path = block.field_path || block.key;
    const value = getValueAtPath(plan, path);
    const emptyObject = value && typeof value === "object" && !Array.isArray(value) && Object.keys(value).length === 0;
    if (value === undefined || value === null || value === "" || emptyObject || (Array.isArray(value) && value.length === 0)) missing.push(path);
  }
  return [...new Set(missing)];
}
