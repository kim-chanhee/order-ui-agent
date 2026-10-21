"""Domain-neutral A2UI component capability declarations."""

PLAN_COMPONENT_TYPES = {
    "text",
    "textarea",
    "number",
    "select",
    "option_cards",
    "multi_select",
    "checkbox",
    "date",
    "date_range",
    "choice",
    "review",
    "notice",
}

RESULT_COMPONENT_TYPES = {
    "text",
    "notice",
    "table",
    "bar_chart",
}

DEFAULT_SUPPORTED_COMPONENTS = PLAN_COMPONENT_TYPES | RESULT_COMPONENT_TYPES

COMPONENT_FALLBACKS = {
    "option_cards": "select",
    "multi_select": "select",
    "choice": "select",
    "date_range": "text",
    "bar_chart": "table",
}
