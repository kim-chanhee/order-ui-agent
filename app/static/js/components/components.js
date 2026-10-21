// 두 모드의 결과 텍스트·안내와, text 타입의 계획 입력 위임을 담당한다.
import { renderTextInput } from "./a2ui/inputs.js?v=plan-sentence-redesign";
import { createElement, createMarkdownParagraph } from "../utils.js?v=plan-sentence-redesign";

export function renderTextComponent(block, context) {
  if (context.surfaceType === "result") {
    return createMarkdownParagraph(block.description || context.result?.answer || block.label || "", { className: "result-text" });
  }
  return renderTextInput(block, context);
}
export function renderNoticeComponent(block) { return createElement("p", { className: "plan-warning plan-field-full", text: block.description || block.label || "확인이 필요합니다." }); }
export function renderUnknownComponent(block) { return createElement("p", { className: "plan-warning plan-field-full", text: `지원되지 않는 구성요소: ${block.type}` }); }
