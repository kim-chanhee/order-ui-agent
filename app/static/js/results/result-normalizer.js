export function normalizeAnalysisResult(response = {}) {
  const executionResult = response.execution_result || response;
  const normalizedSpec = executionResult.normalized_spec || {};
  const analysis = normalizedSpec.analysis_execution || executionResult.analysis_payload || response.analysis_result || {};
  return normalizeAnalysisData({
    ...analysis,
    answer: executionResult.answer || response.message || response.answer || "",
    metadata: {
      ...(analysis.metadata || {}),
      execution_route: normalizedSpec.execution_route || executionResult.provider || "",
      provider: executionResult.provider || "",
      route_reason: normalizedSpec.route_reason || "",
      fallback_used: Boolean(normalizedSpec.fallback_used),
      fallback_error: normalizedSpec.fallback_error || "",
      result_view: (analysis.metadata || {}).result_view || normalizedSpec.analysis_plan?.output?.view || "table",
    },
  });
}

export function normalizeAnalysisData(analysis = {}) {
  const columns = normalizeColumns(analysis.columns || []);
  const rows = normalizeRows(analysis.rows || [], columns);
  const metadata = {
    ...(analysis.metadata || {}),
    result_view: (analysis.metadata || {}).result_view || "table",
  };
  return {
    answer: analysis.answer || "",
    sql: analysis.sql || "",
    params: analysis.params || [],
    columns,
    rows,
    metadata,
    dateFrom: analysis.date_from || null,
    dateTo: analysis.date_to || null,
    anchorEvent: analysis.anchor_event || null,
    anchorTime: analysis.anchor_time || null,
    hasStructuredData: columns.length > 0 && rows.length > 0,
  };
}

function normalizeColumns(columns) {
  if (!Array.isArray(columns)) return [];
  return columns.map((column, index) => {
    const name = typeof column === "string" ? column : column && column.name;
    return name || `column_${index}`;
  });
}

function normalizeRows(rows, columns) {
  if (!Array.isArray(rows)) return [];
  return rows.map((row) => {
    if (Array.isArray(row)) return Object.fromEntries(columns.map((column, index) => [column, row[index]]));
    return row && typeof row === "object" ? row : {};
  });
}
