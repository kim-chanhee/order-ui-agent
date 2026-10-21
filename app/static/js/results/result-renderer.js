import { renderFollowUpActions } from "./a2ui/follow-ups.js?v=plan-sentence-redesign";
import { clearElement, createElement, createMarkdownParagraph, safeText } from "../utils.js?v=plan-sentence-redesign";

const INITIAL_TABLE_ROWS = 50;

export function renderAnalysisResult(result, container, options = {}) {
  const nodes = [];
  if (result.hasStructuredData) {
    if (shouldShowChart(result)) nodes.push(renderChart(result));
    nodes.push(renderTable(result));
  }
  renderResultWithComponents(result, nodes, container, options);
}

export function renderResultWithComponents(result, componentNodes, container, options = {}) {
  clearElement(container);
  const card = createElement("section", { className: "result-card" });
  card.append(renderSummary(result, options.answerInComponent !== true));
  const method = renderAnalysisMethod(result);
  if (method) card.append(method);
  for (const node of componentNodes) if (node) card.append(node);
  const actions = renderFollowUpActions(result, options);
  if (actions) card.append(actions);
  card.append(renderMetadata(result, options));
  container.append(card);
}

export function renderResultTableComponent(_component, context) {
  return renderTable(context.result);
}

export function renderResultBarChartComponent(_component, context) {
  return shouldShowChart(context.result) ? renderChart(context.result) : null;
}

function renderSummary(result, includeAnswer = true) {
  const header = createElement("div", { className: "result-summary" });
  header.append(createElement("h3", { text: "실행 결과" }));
  if (includeAnswer && result.answer) header.append(...renderAnswerBlocks(stripAnswerPrefix(result.answer), { omitTable: result.hasStructuredData }));
  const chips = createElement("div", { className: "result-chips" });
  if (result.rows.length) {
    const returned = Number(result.metadata.returned_row_count) || result.rows.length;
    const rowLabel = result.metadata.result_truncated
      ? `${returned}행 이상 중 ${returned}행 표시`
      : `${returned}행`;
    chips.append(createElement("span", { text: rowLabel }));
  }
  if (result.dateFrom || result.dateTo) chips.append(createElement("span", { text: `${result.dateFrom || "?"} ~ ${result.dateTo || "?"}` }));
  if (result.metadata.metric_kind) chips.append(createElement("span", { text: result.metadata.metric_kind }));
  if (result.metadata.execution_route === "llm_sql_fallback") chips.append(createElement("span", { text: "LLM SQL" }));
  header.append(chips);
  return header;
}

export function renderAnswerBlocks(answer, options = {}) {
  const parsed = parseMarkdownTableAnswer(answer);
  if (!parsed.table) return [markdownParagraph(answer)];
  if (options.omitTable) {
    const summary = [parsed.before, parsed.after].filter(Boolean).join("\n").trim();
    return summary ? [markdownParagraph(summary)] : [];
  }

  const blocks = [];
  if (parsed.before) blocks.push(markdownParagraph(parsed.before));
  const wrapper = createElement("div", { className: "result-table-wrap answer-table-wrap" });
  const table = createElement("table", { className: "result-table answer-table" });
  const thead = createElement("thead");
  const headRow = createElement("tr");
  for (const column of parsed.table.columns) headRow.append(createElement("th", { text: column }));
  thead.append(headRow);
  const tbody = createElement("tbody");
  for (const row of parsed.table.rows) {
    const tr = createElement("tr");
    for (const value of row) tr.append(createElement("td", { text: value }));
    tbody.append(tr);
  }
  table.append(thead, tbody);
  wrapper.append(table);
  blocks.push(wrapper);
  if (parsed.after) blocks.push(markdownParagraph(parsed.after));
  return blocks;
}

const markdownParagraph = createMarkdownParagraph;

export function parseMarkdownTableAnswer(answer) {
  const lines = safeText(answer).split(/\r?\n/);
  const tableStart = lines.findIndex((line, index) => {
    if (!isMarkdownTableRow(line) || index + 1 >= lines.length) return false;
    return isMarkdownSeparatorRow(lines[index + 1]);
  });
  if (tableStart < 0) return { before: safeText(answer).trim(), table: null, after: "" };

  const tableLines = [];
  for (let index = tableStart; index < lines.length; index += 1) {
    if (!isMarkdownTableRow(lines[index])) break;
    tableLines.push(lines[index]);
  }
  const columns = splitMarkdownRow(tableLines[0]);
  const rows = tableLines.slice(2).map(splitMarkdownRow).filter((row) => row.length === columns.length);
  if (!columns.length || !rows.length) return { before: safeText(answer).trim(), table: null, after: "" };

  return {
    before: lines.slice(0, tableStart).join("\n").trim(),
    table: { columns, rows },
    after: lines.slice(tableStart + tableLines.length).join("\n").trim(),
  };
}

function isMarkdownTableRow(line) {
  const trimmed = line.trim();
  return trimmed.startsWith("|") && trimmed.endsWith("|") && trimmed.slice(1, -1).includes("|");
}

function isMarkdownSeparatorRow(line) {
  if (!isMarkdownTableRow(line)) return false;
  return splitMarkdownRow(line).every((cell) => /^:?-{3,}:?$/.test(cell));
}

function splitMarkdownRow(line) {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim().replace(/\\\|/g, "|"));
}

function renderAnalysisMethod(result) {
  if (result.metadata.execution_route !== "llm_sql_fallback") return null;
  const panel = createElement("div", { className: "result-method" });
  panel.append(createElement("strong", { text: "LLM SQL 분석 경로" }));
  panel.append(
    createElement("p", {
      text:
        "이 질문은 정형 검토 UI보다 자유 SQL 분석이 적합하다고 판단되어, LLM이 데이터베이스 스키마를 확인하고 읽기 전용 SQL 경로로 분석했습니다.",
    }),
  );
  const list = createElement("dl");
  list.append(
    createElement("dt", { text: "판단 이유" }),
    createElement("dd", { text: routeReasonLabel(result.metadata.route_reason) }),
  );
  list.append(
    createElement("dt", { text: "안전장치" }),
    createElement("dd", { text: "SELECT/WITH 기반 읽기 전용 실행과 SQL 안전성 검사를 적용합니다." }),
  );
  if (result.metadata.fallback_error) {
    list.append(createElement("dt", { text: "오류" }), createElement("dd", { text: result.metadata.fallback_error }));
  }
  panel.append(list);
  return panel;
}

function renderTable(result) {
  const wrapper = createElement("div", { className: "result-table-wrap" });
  const table = createElement("table", { className: "result-table" });
  const caption = createElement("caption", { text: "분석 결과 표" });
  const thead = createElement("thead");
  const headRow = createElement("tr");
  const allColumns = visibleColumns(result);
  const { commonColumns, detailColumns } = partitionTableColumns(result, allColumns);
  if (commonColumns.length) wrapper.append(renderCommonValues(result, commonColumns));
  const columns = detailColumns.length ? detailColumns : allColumns;
  for (const column of columns) headRow.append(createElement("th", { text: columnLabel(result, column) }));
  thead.append(headRow);
  const tbody = createElement("tbody");
  const appendRows = (rows) => {
    for (const row of rows) {
      const tr = createElement("tr");
      for (const column of columns) {
        const value = row[column];
        const td = createElement("td", { text: formatCell(value, column) });
        if (typeof value === "number") td.classList.add("numeric");
        tr.append(td);
      }
      tbody.append(tr);
    }
  };
  appendRows(result.rows.slice(0, INITIAL_TABLE_ROWS));
  table.append(caption, thead, tbody);
  wrapper.append(table);
  if (result.rows.length > INITIAL_TABLE_ROWS) {
    const remaining = result.rows.length - INITIAL_TABLE_ROWS;
    const button = createElement("button", {
      className: "secondary result-show-more",
      text: `나머지 ${remaining}행 보기`,
      attrs: { type: "button" },
    });
    button.addEventListener("click", () => {
      appendRows(result.rows.slice(INITIAL_TABLE_ROWS));
      button.remove();
    });
    wrapper.append(button);
  }
  return wrapper;
}

function partitionTableColumns(result, columns) {
  if (result.rows.length < 2) return { commonColumns: [], detailColumns: columns };
  const commonColumns = columns.filter((column) => {
    const first = normalizedComparableValue(result.rows[0]?.[column]);
    return result.rows.every((row) => normalizedComparableValue(row?.[column]) === first);
  });
  return {
    commonColumns,
    detailColumns: columns.filter((column) => !commonColumns.includes(column)),
  };
}

function renderCommonValues(result, columns) {
  const panel = createElement("div", { className: "result-common-values" });
  panel.append(createElement("strong", { text: "공통 조건" }));
  for (const column of columns) {
    panel.append(createElement("span", {
      text: `${columnLabel(result, column)}: ${formatCell(result.rows[0]?.[column], column)}`,
    }));
  }
  return panel;
}

function normalizedComparableValue(value) {
  if (value === null || value === undefined) return "";
  return `${typeof value}:${safeText(value)}`;
}

function renderChart(result) {
  const metricColumn = findMetricColumn(result);
  const labelColumn = findLabelColumn(result);
  if (!metricColumn) return createElement("div");
  const values = result.rows.map((row) => Number(row[metricColumn]) || 0);
  const max = Math.max(...values, 1);
  const chart = createElement("div", { className: "result-chart", attrs: { role: "img", "aria-label": "분석 결과 막대 차트" } });
  chart.append(createElement("h4", { text: columnLabel(result, metricColumn) }));
  result.rows.slice(0, 12).forEach((row, index) => {
    const value = Number(row[metricColumn]) || 0;
    const item = createElement("div", { className: "chart-row" });
    item.append(createElement("span", { className: "chart-label", text: safeText(row[labelColumn] ?? `${index + 1}`) }));
    const bar = createElement("span", { className: "chart-bar" });
    bar.style.width = `${Math.max(4, (value / max) * 100)}%`;
    item.append(bar, createElement("span", { className: "chart-value", text: formatCell(value, metricColumn) }));
    chart.append(item);
  });
  if (result.rows.length > 12) chart.append(createElement("small", { className: "chart-disclosure", text: `전체 ${result.rows.length}개 중 상위 12개를 표시합니다.` }));
  return chart;
}

function renderMetadata(result, options) {
  const details = createElement("details", { className: "result-meta" });
  details.append(createElement("summary", { text: "실행 정보" }));
  const list = createElement("dl");
  const items = [
    ["provider", result.metadata.provider],
    ["route", result.metadata.execution_route],
    ["route_reason", result.metadata.route_reason],
    ["typed_plan_skipped", result.metadata.typed_plan_skipped ? "true" : ""],
    ["anchor", result.anchorTime],
  ];
  if (options.debug || document.body.dataset.debug === "true") items.push(["sql", result.sql]);
  for (const [key, value] of items) {
    if (!value) continue;
    list.append(createElement("dt", { text: key }), createElement("dd", { text: Array.isArray(value) ? JSON.stringify(value) : value }));
  }
  details.append(list);
  return details;
}

function findLabelColumn(result) {
  const meta = result.metadata.column_metadata || [];
  const dimension = meta.find((column) => column.role === "dimension" && result.columns.includes(column.name));
  const metric = findMetricColumn(result);
  return dimension?.name || result.columns.find((column) => column !== metric) || result.columns[0];
}

export function shouldShowChart(result) {
  if (!["chart", "table_and_chart"].includes(result.metadata.result_view) || result.rows.length < 2) return false;
  const metric = findMetricColumn(result);
  const label = findLabelColumn(result);
  if (!metric || !label || metric === label) return false;
  const visibleRows = result.rows.slice(0, 12);
  if (!visibleRows.every((row) => Number.isFinite(Number(row[metric])))) return false;
  const labels = visibleRows.map((row) => safeText(row[label]));
  return labels.every(Boolean) && new Set(labels).size === labels.length;
}

function findMetricColumn(result) {
  const meta = result.metadata.column_metadata || [];
  const metric = meta.find((column) => column.role === "metric" && result.columns.includes(column.name));
  if (metric?.name) return metric.name;
  const numeric = result.columns.filter((column) => result.rows.some((row) => typeof row[column] === "number"));
  return numeric.find((column) => /(?:rate|ratio|percent|percentage|비율|율)$/i.test(column)) || numeric[0];
}

function columnLabel(result, column) {
  const meta = (result.metadata.column_metadata || []).find((item) => item.name === column);
  return meta?.label || column.replaceAll("_", " ");
}

function visibleColumns(result) {
  const meta = result.metadata.column_metadata || [];
  const byName = new Map(meta.map((item) => [item.name, item]));
  const percentBases = new Set(result.columns.filter((column) => /_(?:percent|percentage)$/i.test(column)).map((column) => column.replace(/_(?:percent|percentage)$/i, "")));
  return [...result.columns]
    .filter((column) => !percentBases.has(column))
    .filter((column) => byName.get(column)?.hidden !== "true")
    .sort((left, right) => {
      const leftOrder = Number(byName.get(left)?.display_order || 999);
      const rightOrder = Number(byName.get(right)?.display_order || 999);
      if (leftOrder !== rightOrder) return leftOrder - rightOrder;
      return result.columns.indexOf(left) - result.columns.indexOf(right);
    });
}

function formatCell(value, column) {
  if (value === undefined || value === null || value === "") return "-";
  if (typeof value === "number") {
    const formatted = Number.isInteger(value) ? String(value) : value.toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
    return /(?:percent|percentage|퍼센트)$/i.test(column) ? `${formatted}%` : formatted;
  }
  return safeText(value);
}

function stripAnswerPrefix(value) {
  return safeText(value).replace(/^Answer:\s*/i, "");
}

function routeReasonLabel(reason) {
  return reason || "실행 시 데이터베이스 스키마를 확인하는 조회입니다.";
}
