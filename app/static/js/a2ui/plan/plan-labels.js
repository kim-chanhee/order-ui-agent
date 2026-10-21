// Leaf module: Korean label + particle helpers shared by the plan sentence
// builder (plan-sentence.js) and the plan card renderer (plan-renderer.js).
// Imports nothing from ./plan-* so the module graph stays acyclic.
//
// DIMENSION_LABELS / COUNT_FIELD_LABELS mirror _DIMENSION_LABELS /
// _COUNT_FIELD_LABELS in app/planning/option_catalog.py; EVENT_LABELS mirrors
// canonical_value_labels() there. Keep them in sync.

export const UNIT_LABELS = {
  order: "주문", orders: "주문", order_id: "주문",
  customer: "고객", customers: "고객", customer_id: "고객",
  item: "물품", items: "물품", item_id: "물품",
  product: "상품", products: "상품", product_id: "상품",
  package: "패키지", packages: "패키지", package_id: "패키지",
  courier: "배송 기사", couriers: "배송 기사", courier_id: "배송 기사",
  shipper: "배송 기사", shippers: "배송 기사", shipper_id: "배송 기사",
  event: "이벤트", events: "이벤트", event_id: "이벤트",
  employee: "직원", employees: "직원", employee_id: "직원",
};

export function unitLabel(unit) {
  if (!unit) return "항목";
  return UNIT_LABELS[String(unit).trim().toLowerCase()] || String(unit);
}

export const DIMENSION_LABELS = {
  customer_id: "고객별", courier_id: "배송 기사별", shipper_id: "배송 기사별",
  employee_id: "직원별", product_id: "상품별", item_id: "물품별",
  order_id: "주문별", package_id: "패키지별", event_id: "이벤트별",
  event_type: "이벤트 유형별", status: "상태별", day: "일자별",
};

export function dimensionLabel(value) {
  return DIMENSION_LABELS[String(value).trim().toLowerCase()] || `${value}별`;
}

// "고객별" -> "고객"; "일자별" -> "일자". Used when joining multiple dimensions.
export function dimensionStem(value) {
  return dimensionLabel(value).replace(/별$/, "");
}

export const EVENT_LABELS = {
  "failed delivery": "배송 실패",
  "package delivered": "배송 완료",
  "place order": "주문 생성",
  "pay order": "결제",
  "confirm order": "주문 확정",
  "payment reminder": "결제 알림",
  "create package": "포장 생성",
  "send package": "패키지 발송",
  "pick item": "물품 피킹",
  "reorder item": "재주문",
  "item out of stock": "재고 부족",
};

export function semanticLabel(value) {
  const key = String(value).trim().toLowerCase();
  return EVENT_LABELS[key] || String(value);
}

export const COUNT_FIELD_LABELS = {
  event_id: "이벤트", order_id: "주문", item_id: "물품", product_id: "상품",
  package_id: "패키지", customer_id: "고객", courier_id: "배송 기사",
  shipper_id: "배송 기사", employee_id: "직원",
};

export function countFieldLabel(value) {
  if (!value) return "항목";
  const key = String(value).trim().toLowerCase();
  return COUNT_FIELD_LABELS[key] || unitLabel(value);
}

const PRESET_LABELS = {
  last_7_days: "최근 7일", last_14_days: "최근 14일", last_30_days: "최근 30일",
  last_60_days: "최근 60일", last_90_days: "최근 90일",
};

export function presetLabel(preset) {
  return PRESET_LABELS[preset] || "선택한 기간";
}

// A time-scope clause: "최근 30일 동안", "전체 기간 동안", "2024-01-01부터 2024-01-31까지".
export function dateClause(value) {
  if (!value) return null;
  if (value.mode === "all_time") return "전체 기간 동안";
  if (value.mode === "custom") return `${value.date_from || "?"}부터 ${value.date_to || "?"}까지`;
  if (value.mode === "relative") return `최근 ${value.relative_days || "?"}일 동안`;
  if (value.mode === "preset") return `${presetLabel(value.preset)} 동안`;
  return null;
}

const AGG_VERBS = { sum: "합계", avg: "평균", min: "최솟값", max: "최댓값" };

// The metric as a bare noun phrase for the sentence:
// count -> "고유 주문 수", rows -> "상세 목록", sum -> "주문 합계", ratio -> "비율".
export function metricNounPhrase(metric = {}) {
  if (!metric || !metric.kind) return "지표";
  if (metric.kind === "count") {
    if (!metric.unit) return "건수";
    const u = unitLabel(metric.unit);
    const prefix = metric.distinct ? "고유 " : "";
    // The planner sometimes puts a whole phrase in unit ("전체 주문 수"); don't
    // append another "수" onto a token that is already a count noun.
    return /(수|건수|건|개|횟수)$/.test(u) ? `${prefix}${u}` : `${prefix}${u} 수`;
  }
  if (metric.kind === "ratio") {
    const named = String(metric.unit || "").trim();
    if (/[율률]$/.test(named)) return named; // planner-named, e.g. "배송 실패율"
    const n = COUNT_FIELD_LABELS[String(metric.numerator || "").trim().toLowerCase()];
    const d = COUNT_FIELD_LABELS[String(metric.denominator || "").trim().toLowerCase()];
    if (n && d) return `${n} 대비 ${d} 비율`;
    const kw = ratioKeyword(metric.numerator);
    return kw ? `${kw}율` : "비율";
  }
  if (metric.kind === "rows") return "상세 목록";
  const verb = AGG_VERBS[metric.kind];
  if (verb) return metric.unit ? `${unitLabel(metric.unit)} ${verb}` : verb;
  return "지표";
}

// Pull a Korean stem out of a ratio numerator token so a bare ratio can still
// read as "실패율" / "재구매율" instead of a flat "비율".
const RATIO_KEYWORDS = [
  [/fail|실패/, "실패"],
  [/reorder|repurchas|재구매|재주문/, "재구매"],
  [/return|반품/, "반품"],
  [/cancel|취소/, "취소"],
  [/refund|환불/, "환불"],
  [/deliver|배송/, "배송 완료"],
  [/pay|paid|결제/, "결제"],
];

function ratioKeyword(token) {
  const value = String(token || "").toLowerCase();
  if (!value) return null;
  for (const [pattern, label] of RATIO_KEYWORDS) if (pattern.test(value)) return label;
  return null;
}

const SORT_FIELD_LABELS = {
  failure_rate: "실패율", failed_delivery_rate: "실패율", delivery_failure_rate: "실패율",
  ratio: "비율", rate: "비율",
  order_count: "주문 수", failed_count: "실패 건수", count: "건수", total: "합계",
};

export function sortFieldLabel(field) {
  if (!field) return "결과";
  const key = String(field).trim().toLowerCase();
  if (SORT_FIELD_LABELS[key]) return SORT_FIELD_LABELS[key];
  const isRatio = key.includes("rate") || key.includes("ratio");
  if (isRatio && /fail|실패/.test(key)) return "실패율";
  if (isRatio) return "비율";
  if (key.includes("count")) return "건수";
  if (DIMENSION_LABELS[key]) return dimensionStem(key);
  return String(field);
}

// Korean postposition helpers (batchim-aware). jongseong() returns the trailing
// consonant index (0 = none), or -1 for a non-hangul final character.
function jongseong(word) {
  const ch = String(word || "").trim().slice(-1);
  if (!ch) return -1;
  const code = ch.charCodeAt(0);
  if (code < 0xac00 || code > 0xd7a3) return -1;
  return (code - 0xac00) % 28;
}

export function josaEulReul(word) {
  return jongseong(word) > 0 ? "을" : "를";
}

export function josaIGa(word) {
  return jongseong(word) > 0 ? "이" : "가";
}

export function josaWaGwa(word) {
  return jongseong(word) > 0 ? "과" : "와";
}

export function josaEuro(word) {
  const j = jongseong(word);
  return j <= 0 || j === 8 ? "로" : "으로"; // 8 = ㄹ
}
