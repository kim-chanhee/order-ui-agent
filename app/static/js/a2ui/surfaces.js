// A2UI 전용 계획 화면을 편집 상태와 연결하고 확인·수정 동작을 설치한다.
import { renderPlanCard } from "./plan/plan-renderer.js?v=plan-sentence-redesign";
import { normalizeUiPlan } from "./plan/plan-normalizer.js?v=plan-sentence-redesign";
import { validateSurface } from "../surfaces/validation.js";
import { reviewState } from "./state.js?v=plan-sentence-redesign";
import { clone } from "../utils.js?v=plan-sentence-redesign";

export function uiBlockFromSurfaceComponent(component) {
  return {
    ...(clone(component.data_model || {})),
    key: component.component_id,
    type: component.component_type,
  };
}

export function uiPlanFromSurface(surface) {
  validateSurface(surface);
  if (surface.surface_type !== "plan") throw new Error("계획 Surface가 아닙니다.");
  const model = surface.data_model;
  const uiState = model.ui_state || {};
  return normalizeUiPlan({
    summary: model.summary || "",
    analysis_plan: model.analysis_plan || {},
    ui_state: uiState,
    ui_blocks: surface.components.map(uiBlockFromSurfaceComponent),
    missing_fields: model.missing_fields || [],
    suggested_constraints: model.suggested_constraints || [],
    infeasible: model.infeasible || [],
    warnings: model.warnings || [],
    requires_confirmation: model.requires_confirmation !== false,
    surface_id: surface.surface_id,
    plan_id: surface.plan_id,
    revision: surface.revision,
    selected_suggestion_id: uiState.selected_suggestion_id || null,
    refinement_count: Number(uiState.refinement_count || 0),
  });
}

export function installPlanSurface(surface) {
  const currentSurface = clone(validateSurface(surface));
  const uiPlan = uiPlanFromSurface(currentSurface);
  currentSurface.data_model.analysis_plan = uiPlan.analysis_plan;
  currentSurface.data_model.ui_state = uiPlan.ui_state;
  uiPlan.analysis_plan = currentSurface.data_model.analysis_plan;
  uiPlan.ui_state = currentSurface.data_model.ui_state;
  reviewState.currentSurface = currentSurface;
  reviewState.rawUiPlan = null;
  reviewState.currentUiPlan = uiPlan;
  reviewState.currentPlan = currentSurface.data_model.analysis_plan;
  reviewState.initialPlanSnapshot = clone(currentSurface.data_model.analysis_plan);
  return uiPlan;
}

export function renderPlanSurface(container, surface, handlers = {}) {
  const uiPlan = installPlanSurface(surface);
  const actionTypes = new Set((surface.actions || []).map((action) => action?.action_type));
  renderPlanCard(container, uiPlan, {
    onConfirm: actionTypes.has("confirm_plan") ? handlers.onConfirm : undefined,
    onCancel: actionTypes.has("cancel_run") ? handlers.onCancel : undefined,
    onRefine: actionTypes.has("refine_plan") ? handlers.onRefine : undefined,
  });
  return { kind: "plan", uiPlan };
}
