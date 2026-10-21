export async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const payload = data.error || data.detail?.error || {};
    const fieldError = Array.isArray(payload.field_errors) ? payload.field_errors[0] : null;
    const baseMessage = payload.message || data.detail || "요청 처리 중 오류가 발생했습니다.";
    const detail = fieldError?.message
      ? `${fieldError.field || "요청"}: ${fieldError.message}`
      : "";
    const error = new Error(detail ? `${baseMessage} (${detail})` : baseMessage);
    error.status = response.status;
    error.code = payload.code || "";
    error.payload = data;
    throw error;
  }
  return data;
}

export function sendChat(payload) {
  return postJson("/api/chat", payload);
}

export function cancelRun(runId) {
  return fetch(`/api/runs/${encodeURIComponent(runId)}/cancel`, { method: "POST" });
}
