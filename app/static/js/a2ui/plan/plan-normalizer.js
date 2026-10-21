import { clone } from "../../utils.js?v=plan-sentence-redesign";

const ALIASES = {
  event_filter: "multi_select", group_by: "multi_select", metric: "option_cards",
  count_unit: "option_cards", comparison: "choice", sort_by: "select",
  threshold: "number", limit: "number",
};

export function normalizeBlock(rawBlock = {}) {
  const fieldPath = Object.prototype.hasOwnProperty.call(rawBlock, "field_path")
    ? rawBlock.field_path
    : (rawBlock.field ?? rawBlock.key ?? null);
  return {
    ...clone(rawBlock),
    id: rawBlock.id ?? rawBlock.key ?? fieldPath ?? "review",
    key: rawBlock.key ?? fieldPath ?? "review",
    type: ALIASES[rawBlock.type] || rawBlock.type || "review",
    field: fieldPath,
    field_path: fieldPath,
    label: rawBlock.label ?? "",
    description: rawBlock.description ?? rawBlock.help_text ?? "",
    required: Boolean(rawBlock.required),
    required_if: rawBlock.required_if || null,
    visible_if: rawBlock.visible_if || null,
    disabled: Boolean(rawBlock.disabled),
    visible: rawBlock.visible !== false,
    options: Array.isArray(rawBlock.options) ? rawBlock.options : [],
    props: rawBlock.props || {},
    section: rawBlock.section || "primary",
  };
}

export function normalizeAnalysisPlan(rawPlan = {}) {
  const plan = clone(rawPlan || {});
  return {
    ...plan,
    version: plan.version || "4.0",
    original_question: String(plan.original_question || "").trim(),
    analysis_type: plan.analysis_type || "schema_driven_query",
    event_types: Array.isArray(plan.event_types) ? plan.event_types : [],
    target_conditions: Array.isArray(plan.target_conditions) ? plan.target_conditions : [],
    metrics: Array.isArray(plan.metrics) ? plan.metrics : [],
    group_by: normalizeGroupBy(plan.group_by),
    filters: Array.isArray(plan.filters) ? plan.filters : [],
    sort: Array.isArray(plan.sort) ? plan.sort : [],
    unresolved_constraints: Array.isArray(plan.unresolved_constraints) ? plan.unresolved_constraints : [],
    field_metadata: plan.field_metadata || {},
    execution_policy: {
      database_access: "read_only", schema_discovery: true, query_check_required: true,
      relative_time_anchor: "dataset_timeline_max", ...(plan.execution_policy || {}),
    },
    output: { view: "table", include_summary: true, ...(plan.output || {}) },
  };
}

export function normalizeUiPlan(rawUiPlan = {}) {
  const plan = normalizeAnalysisPlan(rawUiPlan.analysis_plan || {});
  return {
    ...clone(rawUiPlan),
    analysis_plan: plan,
    ui_blocks: (rawUiPlan.ui_blocks || []).map(normalizeBlock),
    warnings: Array.isArray(rawUiPlan.warnings) ? rawUiPlan.warnings : [],
    missing_fields: Array.isArray(rawUiPlan.missing_fields) ? [...rawUiPlan.missing_fields] : [],
    suggested_constraints: Array.isArray(rawUiPlan.suggested_constraints) ? rawUiPlan.suggested_constraints.slice(0, 4) : [],
    infeasible: Array.isArray(rawUiPlan.infeasible) ? [...rawUiPlan.infeasible] : [],
  };
}

export function normalizePlanDependencies(plan) { return normalizeAnalysisPlan(plan); }
export function normalizeGroupBy(value) { return Array.isArray(value) ? [...new Set(value.filter(Boolean))] : []; }
