// 공통 앱 진입점: 사용자·채팅·결과 표시를 관리하고 계획 검토는 a2ui/로 위임한다.
import { sendChat, cancelRun } from "./api.js?v=dynamic-blueprint-v1";
import { createReviewController } from "./a2ui/review-controller.js?v=dynamic-blueprint-v1";
import { initializeDefaultComponents, supportedComponentTypes } from "./components/registry.js";
import { renderTextComponent, renderNoticeComponent, renderUnknownComponent } from "./components/components.js?v=dynamic-blueprint-v1";
import { registerReviewComponents } from "./components/a2ui/register.js?v=dynamic-blueprint-v1";
import {
  renderAnswerBlocks, renderResultBarChartComponent,
  renderResultTableComponent,
} from "./results/result-renderer.js?v=result-visibility-v2";
import { renderSurface } from "./surfaces/runtime.js?v=dynamic-blueprint-v1";
import { modeDataFor } from "./modes/mode-data.js?v=dynamic-blueprint-v1";
import {
  collectUserProfile,
  isValidParticipantId,
  loadStoredParticipantId,
  normalizeParticipantId,
  setUserIdentity,
  storeParticipantId,
} from "./modes/user-mode-data.js?v=dynamic-blueprint-v1";
import { appState, beginRun, currentThreadId, endRun } from "./state.js?v=dynamic-blueprint-v1";
import { createElement } from "./utils.js?v=dynamic-blueprint-v1";

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
    dom.stop.disabled = true;
    try {
      await cancelRun(runId);
      if (appState.activeRunId === runId) {
        appState.cancelledRunId = runId;
        addMessage("meta", "요청 중단을 보냈습니다.");
      }
    } catch (error) {
      if (appState.activeRunId === runId) {
        dom.stop.disabled = false;
        addMessage("error", error.message || "중단 요청을 보내지 못했습니다.");
      }
    }
  });
}

async function ask(question) {
  if (appState.isLoading) return;
  if (reviewController.isReviewing()) {
    addMessage("user", question);
    const applied = await reviewController.refineFromChat(question);
    if (applied) dom.question.value = "";
    return;
  }
  const inputSource = appState.inputSource;
  const runId = beginRun();
  setLoading(true);
  addMessage("user", question);
  const loading = addMessage("loading", "처리 중입니다...");
  dom.question.value = "";
  try {
    const modeData = modeDataFor(appState.appMode);
    const response = await sendChat(modeData.buildRequest({
      question,
      thread_id: currentThreadId(),
      input_source: inputSource,
      run_id: runId,
      supported_components: supportedComponents(),
    }, appState));
    if (appState.activeRunId !== runId || appState.cancelledRunId === runId) return;
    const data = modeData.applyResponse(response, appState, inputSource);
    if (data.a2ui_surface?.surface_type === "plan") {
      reviewController.showPlan(question, data);
    } else if (data.a2ui_surface?.surface_type === "result") {
      renderResultMessage(data.a2ui_surface);
    } else if (data.a2ui_surface) {
      throw new Error("지원하지 않는 Surface 응답입니다.");
    } else {
      addMessage("bot", data.answer || "응답을 표시할 수 없습니다.");
    }
  } catch (error) {
    if (appState.activeRunId !== runId || appState.cancelledRunId === runId) return;
    addMessage("error", error.message || "요청 처리 중 오류가 발생했습니다.");
  } finally {
    loading.remove();
    if (endRun(runId)) setLoading(false);
  }
}

function renderResultMessage(surface) {
  const container = addMessage("bot", "");
  container.classList.add("result-message");
  const showFollowUps = surface.data_model?.input_source === "agent2ui";
  renderSurface(container, surface, {
    showFollowUps,
    onFollowUp: showFollowUps ? queueFollowUpQuestion : undefined,
  });
  // Wait for rendering and the loading message removal before positioning the result.
  requestAnimationFrame(() => container.scrollIntoView({ block: "start", behavior: "smooth" }));
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
  dom.stop.disabled = !isLoading || !appState.activeRunId;
  dom.sourceButtons.forEach((button) => { button.disabled = isLoading || reviewController.isReviewing(); });
}

function setPlanReviewActive(isActive) {
  dom.chatForm.hidden = false;
  dom.question.placeholder = isActive ? "수정할 조건을 입력하세요. 예: 최근 30일로 변경" : "예: 가장 최근 데이터 10개를 보여줘";
  dom.submit.textContent = isActive ? "조건 수정" : "질문하기";
  dom.sourceButtons.forEach((button) => {
    button.disabled = isActive || appState.isLoading;
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
