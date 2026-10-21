// 두 모드의 사용자·대화·실행·결과 상태. 계획 편집 상태는 a2ui/state.js에 둔다.
// crypto.randomUUID()는 HTTPS 또는 localhost에서만 사용 가능합니다.
// IP 주소로 접속하는 경우(실험 참가자 등)를 위해 fallback UUID 생성기를 사용합니다.
function generateUUID() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  // RFC 4122 v4 UUID fallback (비보안 컨텍스트 대응)
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

export const appState = {
  appMode: null,
  participantId: null,
  inputSource: "baseline",
  threadIds: {
    baseline: generateUUID(),
    agent2ui: generateUUID(),
  },
  activeRunId: null,
  isLoading: false,
  currentResult: null,
  currentSurface: null,
  participantProfile: null,
  appInitialized: false,
  errors: [],
};

export function currentThreadId() {
  return appState.threadIds[appState.inputSource] || appState.threadIds.baseline;
}

export function beginRun() {
  appState.activeRunId = generateUUID();
  appState.isLoading = true;
  return appState.activeRunId;
}

export function endRun(runId) {
  if (appState.activeRunId !== runId) return false;
  appState.activeRunId = null;
  appState.isLoading = false;
  return true;
}
