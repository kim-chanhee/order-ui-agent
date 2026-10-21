import {
  dateClause, semanticLabel, dimensionLabel, dimensionStem, metricNounPhrase,
  sortFieldLabel, josaEulReul, josaWaGwa, josaIGa,
} from "./plan-labels.js?v=plan-sentence-redesign";

// Build the "search plan in one sentence" as an ordered list of segments so the
// renderer can paint infeasible parts red and keep the sentence live-updating
// from analysis_plan alone (no LLM round-trip — draw() re-runs this on every edit).
//
// Segment = { text, kind, fieldPath?, blocked?, missing? }
//   kind:      "period" | "target" | "group" | "metric" | "sort" | "tail" | "fallback"
//   fieldPath: analysis_plan path this fragment reflects (drives red highlighting)
//   blocked:   fieldPath is in the infeasible set -> render red
//   missing:   a required value is not chosen yet -> render muted (not red)

const COMPUTE_KINDS = new Set(["count", "ratio", "sum", "avg", "min", "max"]);

export function buildPlanSentence(plan = {}, { infeasibleFields = new Set() } = {}) {
  const blocked = (path) => infeasibleFields.has(path);
  const metrics = dedupeMetrics([plan.metric, ...(plan.metrics || [])]);
  const groupBy = Array.isArray(plan.group_by) ? plan.group_by.filter(Boolean) : [];
  const events = [...(plan.event_types || []), ...(plan.target_conditions || [])].filter(Boolean);
  const sort = Array.isArray(plan.sort) ? plan.sort[0] : null;
  const limit = Number.isFinite(plan.limit) ? plan.limit : null;

  const contentCount = (metrics.length ? 1 : 0) + (groupBy.length ? 1 : 0) + (events.length ? 1 : 0);
  if (plan.source === "safe_fallback" || contentCount < 1) {
    return [{ text: fallbackText(plan), kind: "fallback" }];
  }

  const segments = [];

  const period = dateClause(plan.date_range);
  if (period) {
    segments.push({ text: period, kind: "period", fieldPath: "date_range", blocked: blocked("date_range") });
  }

  if (events.length) {
    segments.push({
      text: `${events.map(semanticLabel).join(", ")} 건을 대상으로`,
      kind: "target", fieldPath: "event_types", blocked: blocked("event_types"),
    });
  }

  if (groupBy.length === 1) {
    segments.push({ text: `${dimensionLabel(groupBy[0])}로`, kind: "group", fieldPath: "group_by", blocked: blocked("group_by") });
  } else if (groupBy.length > 1) {
    segments.push({ text: `${groupBy.map(dimensionStem).join("·")}별로`, kind: "group", fieldPath: "group_by", blocked: blocked("group_by") });
  }

  const limitClause = limit ? `상위 ${limit}건을 ` : "";

  if (!metrics.length) {
    segments.push({ text: "분석 지표를 정하면", kind: "metric", fieldPath: "metric.kind", missing: true });
    segments.push({ text: `${limitClause}조회합니다.`, kind: "tail" });
    return segments;
  }

  const phrases = metrics.map(metricNounPhrase);
  let joined;
  if (phrases.length === 1) joined = phrases[0];
  else if (phrases.length === 2) joined = `${phrases[0]}${josaWaGwa(phrases[0])} ${phrases[1]}`;
  else joined = `${phrases[0]}${josaWaGwa(phrases[0])} ${phrases[1]} 등`;

  const metricBlocked = ["metric", "metric.kind", "metric.numerator", "metric.denominator"].some(blocked);
  const obj = `${joined}${josaEulReul(joined)}`;
  const wantsCompute = metrics.some((m) => COMPUTE_KINDS.has(m.kind));

  if (sort && sort.field) {
    const dir = sort.direction === "asc" ? "낮은" : "높은";
    const sortLabel = sortFieldLabel(sort.field);
    // A generic self-reference ("metric"/"value"/"지표") or a key that just
    // restates the metric — drop the label and let "높은 순으로" carry it.
    const selfRef = /^(metric|metrics|value|result|measure|지표|값)$/i.test(String(sort.field).trim());
    const sortText = selfRef || joined.includes(sortLabel)
      ? `${dir} 순으로`
      : `${sortLabel}${josaIGa(sortLabel)} ${dir} 순으로`;
    segments.push({ text: obj, kind: "metric", fieldPath: "metric", blocked: metricBlocked });
    segments.push({ text: "계산하고,", kind: "tail" });
    segments.push({ text: sortText, kind: "sort", fieldPath: "sort" });
    segments.push({ text: `${limitClause}조회합니다.`, kind: "tail" });
  } else {
    segments.push({ text: obj, kind: "metric", fieldPath: "metric", blocked: metricBlocked });
    segments.push({ text: `${limitClause}${wantsCompute ? "계산합니다." : "조회합니다."}`, kind: "tail" });
  }

  return segments;
}

// Curate [metric, ...metrics]: drop a unitless count ("항목 수") when another
// metric already carries the sentence, and collapse duplicate phrasings.
function dedupeMetrics(list) {
  const real = list.filter((m) => m && m.kind);
  const out = [];
  const seen = new Set();
  for (const m of real) {
    if (m.kind === "count" && !m.unit && real.length > 1) continue;
    const phrase = metricNounPhrase(m);
    if (seen.has(phrase)) continue;
    seen.add(phrase);
    out.push(m);
  }
  return out.length ? out : real.slice(0, 1);
}

function fallbackText(plan) {
  return String(plan.summary || "").trim() || "요청하신 분석 계획을 확인해 주세요.";
}
