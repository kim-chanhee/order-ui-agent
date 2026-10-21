import { getValueAtPath } from "../../utils.js?v=plan-sentence-redesign";
import { isBlockRequired, isBlockVisible } from "./condition-evaluator.js?v=plan-sentence-redesign";

export function validatePlanForConfirmation(plan, uiBlocks = [], infeasible = []) {
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
  if (plan.metric?.kind === "ratio" && (!plan.metric.numerator || !plan.metric.denominator)) {
    errors.push({ field: "metric", message: "비율의 분자와 분모를 확인해야 합니다." });
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
