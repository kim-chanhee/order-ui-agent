// A2UI 계획 편집에만 사용하는 입력 위젯과 값 변경 처리.
import { createElement } from "../../utils.js?v=plan-sentence-redesign";

export function renderTextInput(block, context) { return inputComponent(block, context, "text"); }
export function renderTextareaComponent(block, context) { return inputComponent(block, context, "textarea"); }
export function renderNumberComponent(block, context) { return inputComponent(block, context, "number"); }
export function renderDateComponent(block, context) { return inputComponent(block, context, "date"); }

export function renderSelectComponent(block, context) {
  const wrapper = fieldWrapper(block);
  const select = createElement("select");
  select.disabled = block.disabled;
  select.append(createElement("option", { text: "선택", attrs: { value: "" } }));
  for (const option of block.options || []) select.append(createElement("option", { text: option.label || option.value, attrs: { value: option.value } }));
  select.value = context.valueFor(block) ?? "";
  select.addEventListener("change", () => context.update(context.pathFor(block), select.value || null));
  wrapper.append(select);
  return wrapper;
}

export function renderOptionCardsComponent(block, context) {
  const fieldset = createElement("fieldset", { className: "plan-choice-group plan-list-choice" });
  fieldset.append(createElement("legend", { text: block.label || block.key }));
  appendHelp(fieldset, block);
  const chips = createElement("div", { className: "plan-choice-chips" });
  const current = context.valueFor(block);
  for (const option of block.options || []) {
    const label = createElement("label", { className: `plan-choice-chip${current === option.value ? " is-selected" : ""}` });
    const input = createElement("input", { attrs: { type: "radio", name: `plan-${block.key}`, value: option.value } });
    input.checked = current === option.value;
    input.disabled = block.disabled;
    const copy = createElement("span");
    copy.append(createElement("strong", { text: option.label || option.value }));
    if (option.description) copy.append(createElement("small", { text: option.description }));
    // `change` covers picking a new value (mouse or keyboard). A pointer re-click
    // on the already-selected radio fires only `click` (no `change`), so use that
    // to toggle the selection back off.
    input.addEventListener("change", () => {
      if (input.checked && context.valueFor(block) !== option.value) {
        context.update(context.pathFor(block), option.value);
      }
    });
    input.addEventListener("click", () => {
      if (context.valueFor(block) === option.value) context.update(context.pathFor(block), null);
    });
    label.append(input, copy); chips.append(label);
  }
  fieldset.append(chips);
  return fieldset;
}

export function renderMultiSelectComponent(block, context) {
  const fieldset = createElement("fieldset", { className: "plan-choice-group plan-multi-choice" });
  fieldset.append(createElement("legend", { text: block.label || block.key }));
  appendHelp(fieldset, block);
  const chips = createElement("div", { className: "plan-choice-chips" });
  const selected = new Set(Array.isArray(context.valueFor(block)) ? context.valueFor(block) : []);
  for (const option of block.options || []) {
    const label = createElement("label", { className: `plan-choice-chip${selected.has(option.value) ? " is-selected" : ""}` });
    const input = createElement("input", { attrs: { type: "checkbox", value: option.value } });
    input.checked = selected.has(option.value); input.disabled = block.disabled;
    const copy = createElement("span"); copy.append(createElement("strong", { text: option.label || option.value }));
    if (option.description) copy.append(createElement("small", { text: option.description }));
    input.addEventListener("change", () => {
      if (input.checked) selected.add(option.value); else selected.delete(option.value);
      context.update(context.pathFor(block), [...selected]);
    });
    label.append(input, copy); chips.append(label);
  }
  fieldset.append(chips); return fieldset;
}

export function renderCheckboxComponent(block, context) {
  const wrapper = fieldWrapper(block); const input = createElement("input", { attrs: { type: "checkbox" } });
  input.checked = Boolean(context.valueFor(block)); input.disabled = block.disabled;
  input.addEventListener("change", () => context.update(context.pathFor(block), input.checked));
  wrapper.append(input); return wrapper;
}

export function renderDateRangeComponent(block, context) {
  const wrapper = createElement("section", { className: "date-range plan-field-full" });
  wrapper.append(createElement("strong", { text: block.label || "조회 기간" })); appendHelp(wrapper, block);
  const value = context.valueFor(block) || {};
  const mode = value.mode === "all_time" ? "preset" : value.mode || "preset";
  const modes = createElement("div", { className: "date-mode" });
  for (const [key, labelText] of [["preset", "빠른 선택"], ["relative", "최근 N일"], ["custom", "직접 입력"]]) {
    const label = createElement("label"); const input = createElement("input", { attrs: { type: "radio", name: `date-mode-${block.key}`, value: key } });
    input.checked = mode === key; input.addEventListener("change", () => context.update(context.pathFor(block), dateValueForMode(key, value)));
    label.append(input, document.createTextNode(labelText)); modes.append(label);
  }
  wrapper.append(modes);
  const inputs = createElement("div", { className: "date-inputs" });
  if (mode === "preset") {
    const select = createElement("select");
    const presets = [["all_time", "전체 기간"], ["last_7_days", "최근 7일"], ["last_14_days", "최근 14일"], ["last_30_days", "최근 30일"], ["last_60_days", "최근 60일"], ["last_90_days", "최근 90일"]];
    for (const [key, label] of presets) select.append(createElement("option", { text: label, attrs: { value: key } }));
    select.value = value.mode === "all_time" ? "all_time" : value.preset || "";
    select.addEventListener("change", () => context.update(context.pathFor(block), select.value === "all_time" ? { mode: "all_time" } : { mode: "preset", preset: select.value }));
    inputs.append(select);
  } else if (mode === "relative") {
    const input = createElement("input", { attrs: { type: "number", min: 1, max: 3650, value: value.relative_days || "" } });
    input.addEventListener("input", () => context.update(context.pathFor(block), { mode: "relative", relative_days: Number(input.value) || null })); inputs.append(input);
  } else {
    for (const [key, labelText] of [["date_from", "시작일"], ["date_to", "종료일"]]) {
      const label = createElement("label", { text: labelText }); const input = createElement("input", { attrs: { type: "date", value: value[key] || "" } });
      input.addEventListener("input", () => context.update(context.pathFor(block), { ...value, mode: "custom", [key]: input.value || null })); label.append(input); inputs.append(label);
    }
  }
  wrapper.append(inputs, createElement("small", { className: "plan-field-help", text: "최근 기간은 데이터에 기록된 최신일을 기준으로 계산합니다." })); return wrapper;
}

export function renderChoiceComponent(block, context) { return renderOptionCardsComponent(block, context); }
export function renderReviewComponent(_block, context) {
  const node = createElement("section", { className: "plan-review plan-field-full" });
  node.append(createElement("h4", { text: "검토 요약" }), createElement("p", { text: context.plan.original_question || "" })); return node;
}
function inputComponent(block, context, type) {
  const wrapper = fieldWrapper(block); const input = type === "textarea" ? createElement("textarea") : createElement("input", { attrs: { type } });
  const value = context.valueFor(block); if (value !== undefined && value !== null) input.value = value;
  input.disabled = block.disabled; const eventName = type === "number" ? "input" : "input";
  input.addEventListener(eventName, () => context.update(context.pathFor(block), type === "number" ? (Number(input.value) || null) : input.value)); wrapper.append(input); return wrapper;
}
function fieldWrapper(block) { const wrapper = createElement("label", { className: "plan-field" }); wrapper.append(createElement("span", { text: block.label || block.key || "" })); appendHelp(wrapper, block); return wrapper; }
function appendHelp(node, block) { if (block.description) node.append(createElement("small", { className: "plan-field-help", text: block.description })); }
function dateValueForMode(mode, value) {
  if (mode === "relative") return { mode, relative_days: value.relative_days || 30 };
  if (mode === "custom") return { mode, date_from: value.date_from || null, date_to: value.date_to || null };
  return { mode, preset: value.preset || "last_30_days" };
}
