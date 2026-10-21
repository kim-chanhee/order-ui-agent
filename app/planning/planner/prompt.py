"""질문·스키마·이전 분석 후보를 계획 및 UI 생성 프롬프트로 구성한다."""

from __future__ import annotations

import json

from app.a2ui.catalog import PLAN_COMPONENT_TYPES
from app.execution.analysis_semantics import semantic_execution_context
from app.planning.schema_context import PlannerSchemaContext
from app.planning.planner.models import PlannerContextCandidate


def _planner_prompt(
    question: str,
    context: PlannerSchemaContext,
    *,
    context_candidates: list[PlannerContextCandidate] | None = None,
) -> str:
    """질문·스키마·이전 분석 후보와 계획·UI 생성 규칙을 결합해 LLM 요청 프롬프트를 만든다."""

    allowed_components = ", ".join(sorted(PLAN_COMPONENT_TYPES))
    previous_context = ""
    if context_candidates:
        candidate_payload = [
            candidate.model_dump(mode="json")
            for candidate in context_candidates
        ]
        previous_context = (
            "\nSeveral prior successful analyses may be relevant. Treat them as independent scope candidates, "
            "not as one mutable last-known context. Decide semantically whether the current question refers to "
            "one candidate or is standalone. Do not prefer the newest candidate merely because it is newest. "
            "Use question meaning, explicit references, compatible entities, time scope, result identifiers, and "
            "analysis grain. If it is a follow-up, select exactly one context_id and inherit only omitted stable "
            "fields from that candidate. Current user text always wins. If more than one candidate remains "
            "plausible, select the best-supported candidate, set needs_confirmation=true, and lower confidence. "
            "Never combine fields from different candidates.\n"
            "Prior analysis scope candidates:\n"
            + json.dumps(candidate_payload, ensure_ascii=False)
            + "\n"
        )
    return f"""
You are a database-neutral analysis planner. In ONE structured response produce both the semantic
AnalysisPlan and its Dynamic UI Blueprint. Never produce SQL, HTML, JavaScript, table joins, or SQL fragments.
Physical schema is grounding evidence only; plan fields must express user meaning.
The supplied schema is a bounded retrieval seed, not a complete catalog. The execution SQL agent can
inspect additional tables, attributes, and relationships. If the user's business meaning is clear,
express it with semantic labels and do not create unresolved_constraints merely because an exact physical
column, attribute table, identifier mapping, or join is absent from this seed. Reserve unresolved_constraints
for genuinely ambiguous business meaning that would produce materially different analyses.

The response envelope must contain: analysis_plan, ui_blocks, missing_fields, field_metadata,
suggested_constraints, infeasible, summary, warnings, requires_confirmation, and context_resolution. Never place AnalysisPlan fields
such as confidence or unresolved_constraints at the response root.

UX rules:
- summary is ONE Korean sentence describing the search plan (period, target, grouping, metric, sort);
  the UI re-derives it as the user edits, so keep it a faithful plain-language restatement of the plan.
- Prefill values explicitly stated by the user and mark them explicit/user_text.
- Infer only safe meanings; mark uncertain meanings needs_confirmation or missing.
- Only require fields actually necessary for this question. An all-time count may need no date UI.
- Do not add an event_types filter that narrows a total the user asked for (e.g. "전체 주문 수"
  must count all orders, not only "place order" events). Only set event_types when the user's
  target genuinely is a specific business event.
- Mark at most 3 controls section=primary — only the choices a typical user must verify before
  running (usually period, metric, grouping). Every other control is section=advanced.
- Put missing/ambiguous controls first. Do not ask again for already explicit values.
- If a condition the analysis needs cannot be answered from the available data/schema, add a short
  Korean explanation to analysis_plan.unresolved_constraints AND add an entry to `infeasible`
  ({{field_path: the affected AnalysisPlan field or null, label: short Korean noun phrase,
  reason: why it cannot be computed}}). Use this only for genuine data/schema gaps, not for
  meanings the execution SQL agent could still resolve.
- Never invent a group_by / filter dimension the schema has no basis for (customer age bracket,
  gender, region, income tier, marketing channel, weekday name, …). If the user asks to break the
  result down by an attribute that is not an entity id, a status, an event type, or a date/time
  column present in the schema context, do NOT put it in group_by or add a UI option for it — put
  it in `infeasible` (field_path "group_by") and unresolved_constraints instead.
- group_by is always a list and may contain multiple semantic dimensions.
- For every analytical request, state its semantic result contract in analysis_plan:
  target_entity is the business entity returned (for example order, item, product, customer),
  requested_attributes contains canonical roles such as identifier, display_name, price, weight,
  result_grain names what one output row represents (for example distinct_product or item), and
  relationship_scope distinguishes direct_event_link from parent_membership when that distinction
  changes the answer. Populate excluded_attributes when the user requests a narrow attribute such
  as display_name and history/measure fields would be unrelated output. These are semantic roles,
  never physical SQL fragments.
- Treat requests for an entity's name or natural-language "which/what entity" details as
  requested_attributes=["display_name"] unless the user explicitly asks for internal identifiers.
  A name request must not be represented as identifier, price, weight, or change-history output.
- When the user requests names without a grouping or count, use a distinct entity grain so repeated
  event/history rows do not become duplicate output rows.
- A requested-attribute detail list at an explicit result_grain is not a count aggregate: set
  metric=null unless the user separately requests a grouped/summary metric. In a follow-up, a number
  that identifies the previous result set is scope evidence, not by itself a new count instruction.
- metric.kind=count means a distinct semantic entity/event count and must set distinct=true; use
  metric.kind=rows only when the user explicitly asks for physical row occurrences.
- A question may require several analytical stages or outputs (for example a rate used to select a
  group followed by a count/list of that group's details). Put every required metric in metrics and
  keep metric as the primary ranking or headline metric. Do not discard a requested ratio merely
  because the final detail rows use another unit.
- For a metric.kind=ratio, set `unit` to the ratio's short Korean name ending in 율/률
  (e.g. "배송 실패율", "재구매율", "결제 완료율"); this is what the UI sentence shows.
- For a metric.kind=count, `unit` is the short entity noun being counted ("주문", "고객",
  "상품"), never a full phrase like "전체 주문 수".
- A condition/status count means distinct affected business entities at the grain requested by the
  user, not expanded relationship rows. Count a system-event identifier only when event occurrences
  themselves are explicitly requested. Choose identifiers from the grounded schema and relationship grain.
- Relative periods use date_anchor.strategy=dataset_max.
- Use only these whitelisted component types: {allowed_components}. visible_if/required_if use only the condition DSL.
- Every select/option_cards/multi_select/choice block must include concrete, non-empty options grounded in the categorical values already provided above; never leave options empty and never put options in props instead.
- field_path is a path into the AnalysisPlan object itself. It may target only date_range,
  event_types, target_conditions, metric or metric.*, group_by, filters or filters[index].*,
  comparison, sort or sort[index].*, limit, and output or output.*. Never prefix it with
  "analysis_plan." and never target execution_policy, field_metadata, source, confidence,
  original_question, date_anchor, or a field that is not declared by AnalysisPlan.
- General changes such as metric.kind must expose dependent controls with visible_if, so browser clicks need no LLM call.
- Suggest exactly 3 schema-grounded constraints that a user is likely to enter next. Prefer concrete
  values visible in the supplied schema context, keep each suggestion editable, and never auto-apply it.
- The analysis plan must not contain physical SQL, raw_sql, statement, query, SELECT, or JOIN.
- If a required meaning cannot be grounded, put a useful Korean explanation in
  analysis_plan.unresolved_constraints. DynamicPlannerOutput has no top-level unresolved_constraints field.
- Add unresolved_constraints only when no safe executable interpretation exists. If the plan already
  chooses a reasonable interpretation, explain alternatives in summary or warnings and leave
  analysis_plan.unresolved_constraints empty.
- If the question is ordinary conversation rather than a data-analysis request, set requires_confirmation=false,
  return no ui_blocks, and put a short safe conversational response in summary. Otherwise set requires_confirmation=true.
- context_resolution must contain is_followup, selected_context_id, inherit_fields, override_fields,
  reference_evidence, confidence, and needs_confirmation. Decide follow-up meaning semantically from the current
  question and the independent prior scope candidates, never from a fixed phrase list or a recency-only rule.
  For a standalone question, set is_followup=false, selected_context_id=null, and both field lists empty. For a
  follow-up, selected_context_id must exactly match one supplied candidate. List only omitted stable scope in
  inherit_fields. Put fields explicitly replaced by the current question in override_fields. A field may not appear
  in both lists. Never merge scopes from different candidates. Current user text always wins over inherited context.

Runtime schema context (bounded; advisory for semantic grounding):
{context.text}
{semantic_execution_context()}
{previous_context}

Question:
{question}
""".strip()
