// 공통 화면 진입점. 계획 화면은 A2UI 모듈로 위임하고 결과는 두 모드에서 표시한다.
import { renderComponent } from "../components/registry.js";
import { normalizeAnalysisData } from "../results/result-normalizer.js";
import { renderResultWithComponents } from "../results/result-renderer.js?v=plan-sentence-redesign";
import { renderPlanSurface } from "../a2ui/surfaces.js?v=plan-sentence-redesign";
import { validateSurface } from "./validation.js";
import { appState } from "../state.js?v=plan-sentence-redesign";
import { clone } from "../utils.js?v=plan-sentence-redesign";

export function renderSurface(container, surface, handlers = {}) {
  validateSurface(surface);
  if (surface.surface_type === "plan") {
    return renderPlanSurface(container, surface, handlers);
  }
  if (surface.surface_type === "result") {
    const currentSurface = clone(surface);
    const result = normalizeAnalysisData(currentSurface.data_model);
    const context = { surfaceType: "result", surface: currentSurface, result };
    const nodes = currentSurface.components.map((component) => renderComponent({
      ...(component.data_model || {}),
      key: component.component_id,
      type: component.component_type,
    }, context));
    appState.currentSurface = currentSurface;
    appState.currentResult = result;
    const componentTypes = new Set(currentSurface.components.map((component) => component.component_type));
    renderResultWithComponents(result, nodes, container, {
      ...handlers,
      answerInComponent: componentTypes.has("text") || componentTypes.has("notice"),
    });
    return { kind: "result", result };
  }
  throw new Error("지원하지 않는 Surface 유형입니다.");
}
