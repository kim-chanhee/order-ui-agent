import { clone } from "../../utils.js?v=plan-sentence-redesign";
import { normalizeAnalysisPlan } from "./plan-normalizer.js?v=plan-sentence-redesign";

const IGNORED_KEYS = new Set(["source", "confidence", "warnings", "missing_fields"]);

export function diffPlans(initialPlan, currentPlan) {
  const before = normalizeAnalysisPlan(clone(initialPlan || {}));
  const after = normalizeAnalysisPlan(clone(currentPlan || {}));
  const diffs = [];
  compareValue(before, after, "", diffs);
  return diffs;
}

export function changedFieldNames(diff) {
  return (diff || []).map((item) => item.field);
}

function compareValue(before, after, path, diffs) {
  if (path && IGNORED_KEYS.has(path.split(".").at(-1))) return;
  if (Array.isArray(before) || Array.isArray(after)) {
    if (JSON.stringify(before || []) !== JSON.stringify(after || [])) diffs.push({ field: path, before, after });
    return;
  }
  if (isObject(before) || isObject(after)) {
    const keys = new Set([...Object.keys(before || {}), ...Object.keys(after || {})]);
    for (const key of [...keys].sort()) {
      if (IGNORED_KEYS.has(key)) continue;
      compareValue(before?.[key], after?.[key], path ? `${path}.${key}` : key, diffs);
    }
    return;
  }
  if (before !== after) diffs.push({ field: path, before, after });
}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
