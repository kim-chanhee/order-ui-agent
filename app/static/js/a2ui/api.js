// A2UI 계획 확정·추가 조건 수정 API. HTTP 오류 처리는 공통 모듈을 사용한다.
import { postJson } from "../api.js?v=dynamic-blueprint-v1";

export function confirmPlan(payload) {
  return postJson("/api/review/confirm", payload);
}

export function refinePlan(payload) {
  return postJson("/api/review/refine", payload);
}


export function updatePlan(payload) {
  return postJson("/api/review/update", payload);
}
