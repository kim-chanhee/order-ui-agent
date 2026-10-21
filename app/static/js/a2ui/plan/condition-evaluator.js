import { getValueAtPath } from "../../utils.js?v=plan-sentence-redesign";

const OPERATORS = new Set(["eq", "neq", "contains", "not_contains", "in", "exists", "not_empty"]);

export function evaluateCondition(condition, state) {
  if (!condition) return true;
  if (Array.isArray(condition.all)) return condition.all.every((item) => evaluateCondition(item, state));
  if (Array.isArray(condition.any)) return condition.any.some((item) => evaluateCondition(item, state));
  if (!OPERATORS.has(condition.operator) || !condition.path) {
    console.warn("Malformed UI condition, defaulting to false (visible/required):", condition);
    return false;
  }
  const current = getValueAtPath(state, condition.path);
  switch (condition.operator) {
    case "eq": return current === condition.value;
    case "neq": return current !== condition.value;
    case "contains": return Array.isArray(current) || typeof current === "string" ? current.includes(condition.value) : false;
    case "not_contains": return Array.isArray(current) || typeof current === "string" ? !current.includes(condition.value) : true;
    case "in": return Array.isArray(condition.value) ? condition.value.includes(current) : false;
    case "exists": return current !== undefined && current !== null;
    case "not_empty": return current !== undefined && current !== null && current !== "" && (!Array.isArray(current) || current.length > 0);
    default: return false;
  }
}

export function isBlockVisible(block, state) {
  return block.visible !== false && evaluateCondition(block.visible_if, state);
}

export function isBlockRequired(block, state) {
  return Boolean(block.required || (block.required_if && evaluateCondition(block.required_if, state)));
}
