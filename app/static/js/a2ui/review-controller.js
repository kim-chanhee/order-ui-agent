// A2UI 전용 검토 흐름: 화면 표시 → 추가 조건 수정 → 계획 확정·실행.
// 공통 채팅 UI는 전달받은 함수로 조작하며 app.js를 역으로 가져오지 않는다.
import { confirmPlan, refinePlan } from "./api.js?v=plan-sentence-redesign";
import { buildUiPlanRequest, renderPlanCard, prepareUiPlan } from "./plan/plan-renderer.js?v=plan-sentence-redesign";
import { renderSurface } from "../surfaces/runtime.js?v=plan-sentence-redesign";
import { uiPlanFromSurface } from "./surfaces.js?v=plan-sentence-redesign";
import { reviewState } from "./state.js?v=plan-sentence-redesign";
import { appState, beginRun, endRun } from "../state.js?v=plan-sentence-redesign";
import { modeDataFor } from "../modes/mode-data.js?v=plan-sentence-redesign";
import { createElement } from "../utils.js?v=plan-sentence-redesign";

export function createReviewController(ui) {
  const { addMessage, setLoading, setPlanReviewActive, renderResultMessage, supportedComponents } = ui;

  // 새 검토 화면과 이전 형식의 계획 응답을 같은 전용 경로에서 처리한다.
  function showPlan(question, data) {
    if (data.a2ui_surface?.surface_type === "plan") {
      setPlanReviewActive(true);
      const planContainer = addMessage("bot", "");
      const planPresentedAt = performance.now();
      renderSurface(planContainer, data.a2ui_surface, {
        onCancel: () => {
          setPlanReviewActive(false);
          planContainer.remove();
          addMessage("meta", "계획 실행을 취소했습니다.");
        },
        onConfirm: (payload) => {
          setPlanReviewActive(false);
          confirmCurrentPlan(question, payload, planContainer, planPresentedAt);
        },
        onRefine: (text, suggestionId) => refineCurrentPlan(question, text, suggestionId, planContainer, planPresentedAt),
      });
    } else {
      console.warn("Legacy plan response without a2ui_surface");
      setPlanReviewActive(true);
      const planContainer = addMessage("bot", "");
      const uiPlan = prepareUiPlan(data.plan);
      const planPresentedAt = performance.now();
      renderPlanCard(planContainer, uiPlan, {
        onCancel: () => { setPlanReviewActive(false); planContainer.remove(); },
        onConfirm: (payload) => { setPlanReviewActive(false); confirmCurrentPlan(question, payload, planContainer, planPresentedAt); },
        onRefine: (text, suggestionId) => refineCurrentPlan(question, text, suggestionId, planContainer, planPresentedAt),
      });
    }
  }

  async function refineCurrentPlan(question, additionalConstraint, selectedSuggestionId, planContainer, planPresentedAt) {
    const surface = reviewState.currentSurface;
    const current = uiPlanFromSurface(surface);
    const planForRequest = buildUiPlanRequest(current, surface.data_model.analysis_plan);
    const loading = addMessage("loading", "추가 조건을 분석 중입니다...");
    try {
      const data = await refinePlan({
        question,
        thread_id: appState.threadIds.agent2ui,
        plan: planForRequest,
        additional_constraint: additionalConstraint,
        selected_suggestion_id: selectedSuggestionId,
        surface_id: surface.surface_id,
        plan_id: surface.plan_id,
        revision: surface.revision,
        participant_id: appState.participantId,
        participant_profile: appState.participantProfile,
        refinement_count: Number(surface.data_model.ui_state?.refinement_count || 0),
        supported_components: supportedComponents(),
      });
      loading.remove();
      if (data.a2ui_surface?.surface_type !== "plan") throw new Error("수정된 계획 Surface가 없습니다.");
      renderSurface(planContainer, data.a2ui_surface, {
        onCancel: () => { setPlanReviewActive(false); planContainer.remove(); },
        onConfirm: (payload) => { setPlanReviewActive(false); confirmCurrentPlan(question, payload, planContainer, planPresentedAt); },
        onRefine: (text, suggestionId) => refineCurrentPlan(question, text, suggestionId, planContainer, planPresentedAt),
      });
    } catch (error) {
      loading.remove();
      addMessage("error", error.message || "추가 조건을 구조화하지 못했습니다.");
    }
  }

  async function confirmCurrentPlan(question, planPayload, planContainer, planPresentedAt) {
    const runId = beginRun();
    setLoading(true);
    const loading = addMessage("loading", "확정한 계획으로 실행 중입니다...");
    try {
      const modeData = modeDataFor(appState.appMode);
      const data = modeData.applyResponse(await confirmPlan(modeData.buildRequest({
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
      }, appState)), appState, "agent2ui");
      if (!endRun(runId)) return;
      loading.remove();
      reviewState.confirmedPlan = planPayload.analysisPlan;
      planContainer.classList.add("confirmed");
      planContainer.querySelectorAll("button, input, select, textarea").forEach((node) => { node.disabled = true; });
      planContainer.querySelector(".plan-card-head")?.append(createElement("span", { className: "plan-confirmed-badge", text: "실행 완료" }));
      if (data.a2ui_surface?.surface_type !== "result") throw new Error("결과 Surface가 없습니다.");
      renderResultMessage(data.a2ui_surface);
    } catch (error) {
      if (appState.activeRunId === runId) endRun(runId);
      loading.remove();
      addMessage("error", error.message || "실행 중 오류가 발생했습니다.");
    } finally {
      if (appState.activeRunId === runId) endRun(runId);
      setLoading(false);
    }
  }

  return { showPlan };
}
