// A2UI 전용 검토 흐름: 화면 표시 → 추가 조건 수정 → 계획 확정·실행.
// 공통 채팅 UI는 전달받은 함수로 조작하며 app.js를 역으로 가져오지 않는다.
import { confirmPlan, refinePlan, updatePlan } from "./api.js?v=dynamic-blueprint-v1";
import { buildUiPlanRequest } from "./plan/plan-renderer.js?v=dynamic-blueprint-v1";
import { renderSurface } from "../surfaces/runtime.js?v=dynamic-blueprint-v1";
import { uiPlanFromSurface, installPlanSurface, renderInstalledPlan } from "./surfaces.js?v=dynamic-blueprint-v1";
import { reviewState } from "./state.js?v=dynamic-blueprint-v1";
import { appState, beginRun, endRun } from "../state.js?v=dynamic-blueprint-v1";
import { modeDataFor } from "../modes/mode-data.js?v=dynamic-blueprint-v1";
import { createElement } from "../utils.js?v=dynamic-blueprint-v1";

export function createReviewController(ui) {
  const { addMessage, setLoading, setPlanReviewActive, renderResultMessage, supportedComponents } = ui;

  let active = null;
  let updating = false;

  function handlersFor(review) {
    return {
      onCancel: () => { if (active !== review || updating || appState.isLoading) return; active = null; setPlanReviewActive(false); review.container.remove(); addMessage("meta", "계획 실행을 취소했습니다."); },
      onSave: (payload) => saveCurrentPlan(review, payload),
      onConfirm: (payload) => confirmCurrentPlan(review, payload),
      onRefine: (text, suggestionId) => refineCurrentPlan(review, text, suggestionId),
    };
  }

  function showPlan(question, data) {
    if (data.a2ui_surface?.surface_type !== "plan") throw new Error("분석 계획 화면이 없습니다.");
    if (active) active.container.querySelectorAll("button, input, select, textarea").forEach((node) => { node.disabled = true; });
    const review = { question, container: addMessage("bot", ""), presentedAt: performance.now() };
    active = review;
    setPlanReviewActive(true);
    try {
      renderSurface(review.container, data.a2ui_surface, handlersFor(review));
    } catch (error) {
      active = null;
      review.container.remove();
      setPlanReviewActive(false);
      throw error;
    }
  }

  async function saveCurrentPlan(review, payload) {
    if (active !== review || updating) throw new Error("현재 편집 중인 계획이 아닙니다.");
    updating = true; setLoading(true);
    try {
      const data = await updatePlan({
        question: review.question, plan: payload.uiPlan,
        surface_id: payload.surface.surface_id, plan_id: payload.surface.plan_id,
        revision: payload.surface.revision, supported_components: supportedComponents(),
      });
      if (data.a2ui_surface?.surface_type !== "plan") throw new Error("저장된 분석 계획을 받지 못했습니다.");
      installPlanSurface(data.a2ui_surface);
    } finally { updating = false; setLoading(false); }
  }

  async function refineCurrentPlan(review, additionalConstraint, selectedSuggestionId = null) {
    if (active !== review || updating || appState.isLoading) return;
    updating = true; setLoading(true);
    review.container.querySelectorAll("button, input, select, textarea").forEach((node) => { node.disabled = true; });
    const loading = addMessage("loading", "추가 조건을 분석 중입니다...");
    let succeeded = false;
    try {
      const surface = reviewState.currentSurface;
      const current = uiPlanFromSurface(surface);
      const data = await refinePlan({
        question: review.question, thread_id: appState.threadIds.agent2ui,
        plan: buildUiPlanRequest(current, reviewState.currentPlan),
        additional_constraint: additionalConstraint, selected_suggestion_id: selectedSuggestionId,
        surface_id: surface.surface_id, plan_id: surface.plan_id, revision: surface.revision,
        participant_id: appState.participantId, participant_profile: appState.participantProfile,
        refinement_count: Number(surface.data_model.ui_state?.refinement_count || 0),
        supported_components: supportedComponents(),
      });
      if (data.a2ui_surface?.surface_type !== "plan") throw new Error("수정된 분석 계획을 받지 못했습니다.");
      // A natural-language refinement establishes a new recommendation to reset to.
      installPlanSurface(data.a2ui_surface, { resetInitial: true });
      succeeded = data.a2ui_surface.data_model.ui_state?.refinement_applied === true;
    } catch (error) { addMessage("error", error.message || "추가 조건을 반영하지 못했습니다."); }
    finally {
      loading.remove(); updating = false; setLoading(false);
      renderInstalledPlan(review.container, handlersFor(review));
    }
    return succeeded;
  }

  async function confirmCurrentPlan(review, planPayload) {
    const { question, container: planContainer, presentedAt: planPresentedAt } = review;
    if (active !== review || updating) throw new Error("현재 검토 중인 계획이 아닙니다.");
    const runId = beginRun();
    setLoading(true);
    const loading = addMessage("loading", "확정한 계획으로 실행 중입니다...");
    try {
      const modeData = modeDataFor(appState.appMode);
      const response = await confirmPlan(modeData.buildRequest({
        question,
        thread_id: appState.threadIds.agent2ui,
        input_source: "agent2ui",
        run_id: runId,
        plan: planPayload.uiPlan,
        surface_id: planPayload.surface.surface_id,
        plan_id: planPayload.surface.plan_id,
        revision: planPayload.surface.revision,
        selected_suggestion_id: planPayload.surface.selected_suggestion_id,
        refinement_count: planPayload.surface.refinement_count,
        supported_components: supportedComponents(),
        plan_diff: planPayload.clientMetrics.plan_diff,
        client_metrics: {
          ...planPayload.clientMetrics,
          time_to_confirm_ms: Math.round(performance.now() - planPresentedAt),
        },
      }, appState));
      if (appState.activeRunId !== runId || appState.cancelledRunId === runId) return;
      const data = modeData.applyResponse(response, appState, "agent2ui");
      if (data.a2ui_surface?.surface_type !== "result") throw new Error("결과 Surface가 없습니다.");
      const executionMeta = data.execution_result?.normalized_spec?.analysis_execution?.metadata;
      if (executionMeta?.execution_route === "fast_llm_sql_failed" || executionMeta?.failure_stage) {
        throw new Error(executionMeta.fallback_error || "분석을 완료하지 못했습니다. 조건을 확인하거나 다시 실행해 주세요.");
      }
      renderResultMessage(data.a2ui_surface);
      active = null;
      setPlanReviewActive(false);
      planContainer.classList.add("confirmed");
      planContainer.querySelectorAll("button, input, select, textarea").forEach((node) => { node.disabled = true; });
      planContainer.querySelector(".plan-card-head")?.append(createElement("span", { className: "plan-confirmed-badge", text: "실행 완료" }));
    } catch (error) {
      if (appState.activeRunId !== runId || appState.cancelledRunId === runId) return;
      setPlanReviewActive(true);
      throw error;
    } finally {
      loading.remove();
      if (endRun(runId)) setLoading(false);
    }
  }

  return {
    showPlan,
    isReviewing: () => Boolean(active),
    refineFromChat: (text) => active ? refineCurrentPlan(active, text) : Promise.resolve(false),
  };
}
