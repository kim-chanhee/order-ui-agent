// 두 모드의 화면 전송 형식과 필수 필드를 검증한다.
const SURFACE_TYPES = new Set(["plan", "result", "clarification"]);

export function validateSurface(surface) {
  if (!surface || typeof surface !== "object" || Array.isArray(surface)) throw new Error("Surface 형식이 올바르지 않습니다.");
  if (!surface.surface_id || !SURFACE_TYPES.has(surface.surface_type)) throw new Error("Surface 식별자 또는 유형이 올바르지 않습니다.");
  if (!Number.isInteger(surface.revision) || surface.revision < 1) throw new Error("Surface revision이 올바르지 않습니다.");
  if (!surface.data_model || typeof surface.data_model !== "object" || Array.isArray(surface.data_model)) throw new Error("Surface data model이 없습니다.");
  if (!Array.isArray(surface.components)) throw new Error("Surface components가 올바르지 않습니다.");
  for (const component of surface.components) {
    if (!component || typeof component !== "object" || !component.component_id || !component.component_type) {
      throw new Error("Surface component 형식이 올바르지 않습니다.");
    }
  }
  return surface;
}

