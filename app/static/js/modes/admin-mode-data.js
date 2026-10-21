export const ADMIN_MODE = "admin";

export function activateAdminMode(state) {
  state.appMode = ADMIN_MODE;
  state.participantId = null;
  state.participantProfile = null;
}

export function buildAdminRequest(commonFields) {
  return {
    ...commonFields,
    app_mode: ADMIN_MODE,
  };
}

export function applyAdminResponse(response, state, fallbackInputSource) {
  const inputSource = response.input_source || fallbackInputSource;
  if (response.thread_id && inputSource) {
    state.threadIds[inputSource] = response.thread_id;
  }
  return response;
}
