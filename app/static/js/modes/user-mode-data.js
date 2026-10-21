export const USER_MODE = "user";
export const PARTICIPANT_ID_STORAGE_KEY = "orderUiParticipantId";

export function activateUserMode(state) {
  state.appMode = USER_MODE;
}

export function setUserIdentity(state, participantId, participantProfile) {
  state.appMode = USER_MODE;
  state.participantId = participantId;
  state.participantProfile = participantProfile;
}

export function buildUserRequest(commonFields, state) {
  return {
    ...commonFields,
    app_mode: USER_MODE,
    task_id: null,
    participant_id: state.participantId,
    participant_profile: state.participantProfile,
  };
}

export function applyUserResponse(response, state, fallbackInputSource) {
  const inputSource = response.input_source || fallbackInputSource;
  if (response.thread_id && inputSource) {
    state.threadIds[inputSource] = response.thread_id;
  }
  return response;
}

export function collectUserProfile(formData) {
  const aiTools = formData.getAll("ai_tools");
  const other = String(formData.get("ai_tools_other") || "").trim();
  if (!aiTools.length && !other) return null;
  return {
    gender: formData.get("gender"),
    age: formData.get("age"),
    education: formData.get("education"),
    occupation: String(formData.get("occupation") || "").trim(),
    ai_experience: formData.get("ai_experience"),
    llm_frequency: formData.get("llm_frequency"),
    ai_tools: aiTools,
    ai_tools_other: other,
  };
}

export function normalizeParticipantId(value) {
  return String(value || "").trim().toUpperCase();
}

export function isValidParticipantId(value) {
  return /^P\d{3,}$/.test(value);
}

export function loadStoredParticipantId(storage) {
  try {
    const target = storage ?? globalThis.sessionStorage;
    return normalizeParticipantId(target.getItem(PARTICIPANT_ID_STORAGE_KEY));
  } catch {
    return "";
  }
}

export function storeParticipantId(participantId, storage) {
  try {
    const target = storage ?? globalThis.sessionStorage;
    target.setItem(PARTICIPANT_ID_STORAGE_KEY, participantId);
    return true;
  } catch {
    return false;
  }
}
