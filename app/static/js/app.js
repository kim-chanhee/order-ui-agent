// 공통 앱 진입점: 사용자·채팅·결과 표시를 관리하고 계획 검토는 a2ui/로 위임한다.
import { sendChat, cancelRun } from "./api.js?v=plan-sentence-redesign";
import { createReviewController } from "./a2ui/review-controller.js?v=plan-sentence-redesign";
import { initializeDefaultComponents, supportedComponentTypes } from "./components/registry.js";
import { renderTextComponent, renderNoticeComponent, renderUnknownComponent } from "./components/components.js?v=plan-sentence-redesign";
import { registerReviewComponents } from "./components/a2ui/register.js?v=plan-sentence-redesign";
import { normalizeAnalysisResult } from "./results/result-normalizer.js";
import {
  renderAnalysisResult, renderAnswerBlocks, renderResultBarChartComponent,
  renderResultTableComponent,
} from "./results/result-renderer.js?v=plan-sentence-redesign";
import { renderSurface } from "./surfaces/runtime.js?v=plan-sentence-redesign";
import { modeDataFor } from "./modes/mode-data.js?v=plan-sentence-redesign";
import {
  collectUserProfile,
  isValidParticipantId,
  loadStoredParticipantId,
  normalizeParticipantId,
  setUserIdentity,
  storeParticipantId,
} from "./modes/user-mode-data.js?v=plan-sentence-redesign";
import { appState, beginRun, currentThreadId, endRun } from "./state.js?v=plan-sentence-redesign";
import { createElement } from "./utils.js?v=plan-sentence-redesign";

const dom = {
  modeGate: document.querySelector("#mode-gate"),
  surveyGate: document.querySelector("#survey-gate"),
  appShell: document.querySelector("#app-shell"),
  profileForm: document.querySelector("#profile-form"),
  profileError: document.querySelector("#profile-error"),
  participantId: document.querySelector("#participant-id"),
  participantIdError: document.querySelector("#participant-id-error"),
  surveyBack: document.querySelector("#survey-back"),
  chat: document.querySelector("#chat"),
  chatForm: document.querySelector("#chat-form"),
  captureToggle: document.querySelector("#capture-toggle"),
  question: document.querySelector("#question"),
  submit: document.querySelector("#submit"),
  stop: document.querySelector("#stop"),
  sourceButtons: [...document.querySelectorAll("[data-input-source]")],
  steps: [...document.querySelectorAll("[data-step]")],
};

initializeDefaultComponents({
  text: renderTextComponent, notice: renderNoticeComponent, unknown: renderUnknownComponent,
  table: renderResultTableComponent, bar_chart: renderResultBarChartComponent,
});
registerReviewComponents();
const reviewController = createReviewController({
  addMessage, setLoading, setPlanReviewActive, renderResultMessage, supportedComponents,
});
bindUi();

function bindUi() {
  const storedParticipantId = loadStoredParticipantId();
  if (storedParticipantId && dom.participantId) {
    dom.participantId.value = storedParticipantId;
  }
  dom.participantId?.addEventListener("input", () => {
    dom.participantId.value = dom.participantId.value.toUpperCase().replace(/\s+/g, "");
    dom.participantIdError.hidden = true;
  });
  document.querySelectorAll("[data-app-mode]").forEach((button) => {
    button.addEventListener("click", () => {
      const appMode = button.dataset.appMode;
      modeDataFor(appMode).activate(appState);
      if (appMode === "admin") {
        showChat();
      } else {
        showSurvey();
      }
    });
  });
  dom.surveyBack?.addEventListener("click", () => showMode());
  dom.profileForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(dom.profileForm);
    const participantId = normalizeParticipantId(formData.get("participant_id"));
    if (!isValidParticipantId(participantId)) {
      dom.participantIdError.hidden = false;
      dom.participantId?.focus();
      return;
    }
    dom.participantIdError.hidden = true;
    const profile = collectUserProfile(formData);
    if (!profile) {
      dom.profileError.hidden = false;
      return;
    }
    dom.profileError.hidden = true;
    setUserIdentity(appState, participantId, profile);
    storeParticipantId(participantId);
    showChat();
  });
  dom.sourceButtons.forEach((button) => button.addEventListener("click", () => setInputSource(button.dataset.inputSource)));
  dom.captureToggle?.addEventListener("click", () => {
    const expanded = dom.chat?.classList.toggle("chat--capture");
    dom.captureToggle.setAttribute("aria-pressed", expanded ? "true" : "false");
    dom.captureToggle.textContent = expanded ? "캡처용 전체보기 끄기" : "캡처용 전체보기";
  });
  dom.chatForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    const question = dom.question.value.trim();
    if (question) ask(question);
  });
  dom.question?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
    event.preventDefault();
    if (!dom.submit.disabled) dom.chatForm.requestSubmit();
  });
  dom.stop?.addEventListener("click", async () => {
    const runId = appState.activeRunId;
    if (!runId) return;
    await cancelRun(runId).catch(() => {});
    endRun(runId);
    setLoading(false);
    addMessage("meta", "요청 중단을 보냈습니다.");
  });
}

async function ask(question) {
  const runId = beginRun();
  setLoading(true);
  addMessage("user", question);
  const loading = addMessage("loading", "처리 중입니다...");
  dom.question.value = "";
  try {
    const modeData = modeDataFor(appState.appMode);
    const data = modeData.applyResponse(await sendChat(modeData.buildRequest({
      question,
      thread_id: currentThreadId(),
      input_source: appState.inputSource,
      run_id: runId,
      supported_components: supportedComponents(),
    }, appState)), appState, appState.inputSource);
    if (!endRun(runId)) return;
    loading.remove();
    if (data.a2ui_surface?.surface_type === "plan") {
      reviewController.showPlan(question, data);
    } else if (data.a2ui_surface?.surface_type === "result") {
      renderResultMessage(data.a2ui_surface);
    } else if (data.a2ui_surface) {
      throw new Error("지원하지 않는 Surface 응답입니다.");
    } else if (data.plan) {
      reviewController.showPlan(question, data);
    } else if (data.execution_result && data.execution_result.kind !== "conversation") {
      console.warn("Legacy result response without a2ui_surface");
      renderLegacyResultMessage(data);
    } else {
      addMessage("bot", data.answer || "응답을 표시할 수 없습니다.");
    }
  } catch (error) {
    if (appState.activeRunId === runId) endRun(runId);
    loading.remove();
    addMessage("error", error.message || "요청 처리 중 오류가 발생했습니다.");
  } finally {
    if (appState.activeRunId === runId) endRun(runId);
    setLoading(false);
  }
}

function renderResultMessage(surface) {
  const container = addMessage("bot", "");
  const showFollowUps = surface.data_model?.input_source === "agent2ui";
  renderSurface(container, surface, {
    showFollowUps,
    onFollowUp: showFollowUps ? queueFollowUpQuestion : undefined,
  });
}

function renderLegacyResultMessage(data) {
  const container = addMessage("bot", "");
  const result = normalizeAnalysisResult(data);
  appState.currentResult = result;
  const showFollowUps = data.input_source === "agent2ui";
  renderAnalysisResult(result, container, {
    showFollowUps,
    onFollowUp: showFollowUps ? queueFollowUpQuestion : undefined,
  });
}

function queueFollowUpQuestion(question) {
  dom.question.value = question;
  dom.question.focus();
  dom.question.scrollIntoView({ block: "nearest" });
}

function addMessage(type, text) {
  const message = createElement("div", { className: `msg ${type}` });
  if (text) {
    if (type === "bot") {
      message.append(...renderAnswerBlocks(text));
    } else {
      message.textContent = text;
    }
  }
  dom.chat.append(message);
  dom.chat.scrollTop = dom.chat.scrollHeight;
  return message;
}

function setInputSource(inputSource) {
  appState.inputSource = inputSource;
  dom.sourceButtons.forEach((button) => button.classList.toggle("active", button.dataset.inputSource === inputSource));
}

function setLoading(isLoading) {
  appState.isLoading = isLoading;
  dom.submit.disabled = isLoading;
  dom.stop.disabled = !isLoading;
}

function setPlanReviewActive(isActive) {
  dom.chatForm.hidden = isActive;
  dom.sourceButtons.forEach((button) => {
    button.disabled = isActive;
  });
}

function showMode() {
  dom.modeGate.hidden = false;
  dom.surveyGate.hidden = true;
  dom.appShell.hidden = true;
  setStep("mode");
}

function showSurvey() {
  dom.modeGate.hidden = true;
  dom.surveyGate.hidden = false;
  dom.appShell.hidden = true;
  setStep("survey");
}

function showChat() {
  dom.modeGate.hidden = true;
  dom.surveyGate.hidden = true;
  dom.appShell.hidden = false;
  setStep("chat");
}

function setStep(step) {
  dom.steps.forEach((node) => node.classList.toggle("active", node.dataset.step === step));
}

function supportedComponents() {
  return supportedComponentTypes();
}
