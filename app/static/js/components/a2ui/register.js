// A2UI 편집용 컴포넌트만 공통 레지스트리에 등록한다.
import { initializeDefaultComponents } from "../registry.js";
import {
  renderTextareaComponent, renderNumberComponent, renderSelectComponent,
  renderOptionCardsComponent, renderMultiSelectComponent, renderCheckboxComponent,
  renderDateComponent, renderDateRangeComponent, renderChoiceComponent, renderReviewComponent,
} from "./inputs.js?v=plan-sentence-redesign";

export function registerReviewComponents() {
  initializeDefaultComponents({
    textarea: renderTextareaComponent, number: renderNumberComponent, select: renderSelectComponent,
    option_cards: renderOptionCardsComponent, multi_select: renderMultiSelectComponent,
    checkbox: renderCheckboxComponent, date: renderDateComponent,
    date_range: renderDateRangeComponent, choice: renderChoiceComponent, review: renderReviewComponent,
  });
}
