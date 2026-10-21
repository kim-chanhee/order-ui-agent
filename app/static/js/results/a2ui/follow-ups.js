// A2UI 결과 화면의 후속 분석 버튼. 표·차트 렌더러와 독립적으로 관리한다.
import { createElement } from "../../utils.js?v=plan-sentence-redesign";

export function renderFollowUpActions(result, options) {
  if (options.showFollowUps === false || typeof options.onFollowUp !== "function" || !result.hasStructuredData) return null;
  const prompts = followUpPrompts(result);
  if (!prompts.length) return null;
  const actions = createElement("div", { className: "result-actions", attrs: { "aria-label": "후속 분석" } });
  actions.append(createElement("strong", { text: "다음 분석" }));
  for (const item of prompts) {
    const button = createElement("button", { className: "secondary", text: item.label, attrs: { type: "button" } });
    button.addEventListener("click", () => options.onFollowUp(item.prompt));
    actions.append(button);
  }
  return actions;
}

export function followUpPrompts(result) {
  void result;
  return [];
}

