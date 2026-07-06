const ROWS = "ABCDEFGH".split("");
const COLS = Array.from({ length: 12 }, (_, i) => i + 1);
const WELLS = ROWS.flatMap((row) => COLS.map((col) => `${row}${col}`));
const GROUP_COLORS = [
  "#2f6fed",
  "#1f8a99",
  "#b54762",
  "#8a6f1f",
  "#6d5bd0",
  "#17805f",
  "#c05a2b",
  "#48627a",
  "#9b4d8b",
  "#527a2e",
];

let jobId = null;
let detectedWells = new Set();
let selectedWells = new Set();
let plateMap = WELLS.map((well) => ({ well, condition: "", treatment: "", dose: "", replicate: "", group: "", role: "", notes: "" }));
let latestProcessed = [];
let latestMetrics = [];
let isDraggingPlate = false;
let dragMode = "select";

const rawFileInput = document.querySelector("#rawFileInput");
const parseStatus = document.querySelector("#parseStatus");
const parseWarnings = document.querySelector("#parseWarnings");
const detectedWellCount = document.querySelector("#detectedWellCount");
const detectedWellSummary = document.querySelector("#detectedWellSummary");
const plateId = document.querySelector("#plateId");
const previewRowCount = document.querySelector("#previewRowCount");
const previewHead = document.querySelector("#previewHead");
const previewBody = document.querySelector("#previewBody");
const plateGrid = document.querySelector("#plateGrid");
const selectionCount = document.querySelector("#selectionCount");
const labelForm = document.querySelector("#labelForm");
const analyzeButton = document.querySelector("#analyzeButton");
const analysisStatus = document.querySelector("#analysisStatus");
const resultsSection = document.querySelector("#resultsSection");
const downloads = document.querySelector("#downloads");
const qcWarnings = document.querySelector("#qcWarnings");
const metricsHead = document.querySelector("#metricsHead");
const metricsBody = document.querySelector("#metricsBody");
const labelLegend = document.querySelector("#labelLegend");

function setWarnings(container, warnings) {
  container.innerHTML = "";
  (warnings || []).forEach((warning) => {
    const div = document.createElement("div");
    div.textContent = warning;
    container.appendChild(div);
  });
}

function errorMessagesFromPayload(payload) {
  const detail = payload?.detail;
  if (typeof detail === "string") return [detail];
  if (detail && Array.isArray(detail.errors)) return detail.errors;
  if (detail && typeof detail.message === "string") return [detail.message];
  return ["Request failed"];
}

async function readPayload(response) {
  const text = await response.text();
  try {
    return JSON.parse(text);
  } catch {
    return { detail: text };
  }
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 45000) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    window.clearTimeout(timeout);
  }
}

function renderTable(headEl, bodyEl, rows, maxCols = 10) {
  headEl.innerHTML = "";
  bodyEl.innerHTML = "";
  if (!rows || !rows.length) return;
  const columns = Object.keys(rows[0]).slice(0, maxCols);
  const tr = document.createElement("tr");
  columns.forEach((col) => {
    const th = document.createElement("th");
    th.textContent = col;
    tr.appendChild(th);
  });
  headEl.appendChild(tr);
  rows.slice(0, 100).forEach((row) => {
    const bodyRow = document.createElement("tr");
    columns.forEach((col) => {
      const td = document.createElement("td");
      td.textContent = row[col] ?? "";
      bodyRow.appendChild(td);
    });
    bodyEl.appendChild(bodyRow);
  });
}

function mapRecord(well) {
  return plateMap.find((item) => item.well === well);
}

function rowThenColumnSort(a, b) {
  return ROWS.indexOf(a[0]) - ROWS.indexOf(b[0]) || Number(a.slice(1)) - Number(b.slice(1));
}

function groupLabel(rec) {
  if (!rec) return "";
  return [rec.condition, rec.treatment, rec.dose, rec.group, rec.role]
    .map((value) => String(value || "").trim())
    .filter(Boolean)
    .join(" | ");
}

function groupColorMap() {
  const labels = [...new Set(plateMap.map(groupLabel).filter(Boolean))].sort();
  return new Map(labels.map((label, index) => [label, GROUP_COLORS[index % GROUP_COLORS.length]]));
}

function renderDetectedWellSummary() {
  detectedWellSummary.innerHTML = "";
  if (!detectedWells.size) return;

  const card = document.createElement("div");
  card.className = "detected-summary-card";
  const title = document.createElement("strong");
  title.textContent = "Detected plate coverage";
  card.appendChild(title);

  const rows = document.createElement("div");
  rows.className = "detected-row-list";
  ROWS.forEach((row) => {
    const count = COLS.filter((col) => detectedWells.has(`${row}${col}`)).length;
    const pill = document.createElement("span");
    pill.className = count ? "detected-pill" : "detected-pill empty";
    pill.textContent = `${row}: ${count}/12`;
    rows.appendChild(pill);
  });
  card.appendChild(rows);

  const missing = WELLS.filter((well) => !detectedWells.has(well));
  if (missing.length && missing.length <= 24) {
    const missingList = document.createElement("div");
    missingList.className = "detected-missing-list";
    missing.slice(0, 24).forEach((well) => {
      const pill = document.createElement("span");
      pill.className = "detected-pill empty";
      pill.textContent = well;
      missingList.appendChild(pill);
    });
    card.appendChild(missingList);
  }

  detectedWellSummary.appendChild(card);
}

function renderLabelLegend(colors) {
  labelLegend.innerHTML = "";
  colors.forEach((color, label) => {
    const item = document.createElement("span");
    item.className = "label-legend-item";
    item.style.setProperty("--plate-color", color);
    const swatch = document.createElement("i");
    swatch.className = "label-legend-swatch";
    const text = document.createElement("span");
    text.textContent = label;
    item.append(swatch, text);
    labelLegend.appendChild(item);
  });
}

function renderPlate() {
  plateGrid.innerHTML = "";
  const colors = groupColorMap();
  plateGrid.appendChild(document.createElement("div"));
  COLS.forEach((col) => {
    const axis = document.createElement("div");
    axis.className = "plate-axis";
    axis.textContent = col;
    plateGrid.appendChild(axis);
  });
  ROWS.forEach((row) => {
    const rowAxis = document.createElement("div");
    rowAxis.className = "plate-axis";
    rowAxis.textContent = row;
    plateGrid.appendChild(rowAxis);
    COLS.forEach((col) => {
      const well = `${row}${col}`;
      const rec = mapRecord(well);
      const label = groupLabel(rec);
      const cell = document.createElement("button");
      cell.type = "button";
      cell.className = "plate-cell";
      cell.dataset.well = well;
      if (label && colors.has(label)) cell.style.setProperty("--plate-color", colors.get(label));
      if (detectedWells.has(well)) cell.classList.add("detected");
      if (selectedWells.has(well)) cell.classList.add("selected");
      if (rec && rec.condition) cell.classList.add("labeled");
      if (rec && rec.role === "blank") cell.classList.add("blank");
      if (rec && rec.role === "vehicle") cell.classList.add("vehicle");
      if (rec && rec.role === "control") cell.classList.add("control");
      cell.textContent = well;
      cell.title = label ? `${well}: ${label}` : well;
      plateGrid.appendChild(cell);
    });
  });
  renderLabelLegend(colors);
}

function setWellSelected(well, shouldSelect) {
  if (!well) return;
  if (shouldSelect) selectedWells.add(well);
  else selectedWells.delete(well);
  const cell = plateGrid.querySelector(`[data-well="${CSS.escape(well)}"]`);
  if (cell) cell.classList.toggle("selected", shouldSelect);
  updateSelectionCount();
}

function wellFromEvent(event) {
  const target = event.target.closest(".plate-cell");
  return target ? target.dataset.well : null;
}

function startPlateDrag(event) {
  const well = wellFromEvent(event);
  if (!well) return;
  event.preventDefault();
  isDraggingPlate = true;
  dragMode = selectedWells.has(well) ? "deselect" : "select";
  if (!event.shiftKey && !event.metaKey && !event.ctrlKey) {
    selectedWells.clear();
    plateGrid.querySelectorAll(".plate-cell.selected").forEach((cell) => cell.classList.remove("selected"));
    dragMode = "select";
  }
  setWellSelected(well, dragMode === "select");
}

function continuePlateDrag(event) {
  if (!isDraggingPlate) return;
  const well = wellFromEvent(event);
  if (!well) return;
  setWellSelected(well, dragMode === "select");
}

function endPlateDrag() {
  isDraggingPlate = false;
}

function updateSelectionCount() {
  if (!selectedWells.size) {
    selectionCount.textContent = "No wells selected";
    return;
  }
  const sorted = [...selectedWells].sort(rowThenColumnSort);
  const preview = sorted.slice(0, 6).join(", ");
  const suffix = sorted.length > 6 ? ` +${sorted.length - 6}` : "";
  selectionCount.textContent = `${selectedWells.size} selected: ${preview}${suffix}`;
}

function applyLabels() {
  if (!selectedWells.size) return;
  const form = new FormData(labelForm);
  selectedWells.forEach((well) => {
    const rec = mapRecord(well);
    ["condition", "treatment", "dose", "replicate", "group", "role", "notes"].forEach((key) => {
      const value = form.get(key);
      if (value !== null && String(value).trim() !== "") rec[key] = String(value).trim();
    });
  });
  renderPlate();
  updateSelectionCount();
}

function downloadText(filename, text, type = "text/plain") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function plateMapCsv() {
  const cols = ["well", "condition", "treatment", "dose", "replicate", "group", "role", "notes"];
  return [cols.join(","), ...plateMap.map((row) => cols.map((col) => `"${String(row[col] || "").replace(/"/g, '""')}"`).join(","))].join("\n");
}

function parseCsv(text) {
  const lines = text.trim().split(/\r?\n/);
  const headers = lines.shift().split(",").map((h) => h.replace(/^"|"$/g, ""));
  return lines.map((line) => {
    const values = line.match(/("([^"]|"")*"|[^,]+)/g) || [];
    const rec = {};
    headers.forEach((header, index) => {
      rec[header] = (values[index] || "").replace(/^"|"$/g, "").replace(/""/g, '"');
    });
    return rec;
  });
}

function settingsPayload() {
  const form = new FormData(document.querySelector("#settingsForm"));
  const numberOrNull = (name) => {
    const value = form.get(name);
    return value === "" || value === null ? null : Number(value);
  };
  return {
    blank_subtraction: { enabled: form.get("blankEnabled") === "on", mode: form.get("blankMode") },
    baseline_normalization: { enabled: form.get("baselineEnabled") === "on", mode: form.get("baselineMode") },
    control_normalization: { enabled: form.get("controlEnabled") === "on", mode: form.get("controlMode") },
    metrics: {
      start_time: numberOrNull("startTime"),
      end_time: numberOrNull("endTime"),
      early_end_time: numberOrNull("earlyEndTime"),
      late_start_time: numberOrNull("lateStartTime"),
      value_column: "analysis_value",
    },
    statistics: { metric: "endpoint", group_by: "condition" },
    export_metric: "endpoint",
  };
}

function updateSettingStates() {
  document.querySelectorAll(".setting-card").forEach((card) => {
    const checkbox = card.querySelector(".setting-toggle input[type='checkbox']");
    if (!checkbox) return;
    const enabled = checkbox.checked;
    card.classList.toggle("inactive", !enabled);
    card.querySelectorAll("select").forEach((select) => {
      select.disabled = !enabled;
    });
  });
}

function validateAnalysisSetup(settings) {
  const detected = detectedWells.size ? detectedWells : new Set(WELLS);
  const activeLabels = plateMap.filter((rec) => detected.has(rec.well));
  const roles = activeLabels.map((rec) => String(rec.role || "").trim().toLowerCase());
  const hasCondition = activeLabels.some((rec) => String(rec.condition || "").trim());
  const errors = [];

  if (!hasCondition) {
    errors.push("Label at least one detected well with a condition before analyzing.");
  }
  if (settings.blank_subtraction.enabled && !roles.includes("blank")) {
    errors.push("Blank subtraction is enabled, but no detected wells are marked as blank.");
  }
  if (settings.control_normalization.enabled && !roles.some((role) => role === "vehicle" || role === "control")) {
    errors.push("Vehicle/control normalization is enabled, but no detected wells are marked as vehicle or control.");
  }
  return errors;
}

function addDownloadLinks(downloadMap) {
  downloads.innerHTML = "";
  Object.entries(downloadMap || {}).forEach(([key, href]) => {
    const link = document.createElement("a");
    link.href = href;
    link.textContent = key.replaceAll("_", " ");
    downloads.appendChild(link);
  });
}

function plotTimecourse(rows) {
  const el = document.querySelector("#timecoursePlot");
  const data = rows.filter((r) => r.time !== undefined && r.mean !== undefined);
  if (!data.length) {
    el.textContent = "No summary rows to plot.";
    return;
  }
  const groups = [...new Set(data.map((r) => r.condition || r.group || "unlabeled"))];
  const times = data.map((r) => Number(r.time));
  const vals = data.map((r) => Number(r.mean));
  const width = 560, height = 260, pad = 40;
  const minT = Math.min(...times), maxT = Math.max(...times);
  const minY = Math.min(...vals), maxY = Math.max(...vals);
  const sx = (x) => pad + ((x - minT) / Math.max(1, maxT - minT)) * (width - pad * 2);
  const sy = (y) => height - pad - ((y - minY) / Math.max(1, maxY - minY)) * (height - pad * 2);
  const colors = ["#2f6fed", "#7c5cc4", "#1f8a99", "#b56b1d", "#b54762"];
  const series = groups.map((group, i) => {
    const pts = data.filter((r) => (r.condition || r.group || "unlabeled") === group).sort((a, b) => Number(a.time) - Number(b.time));
    const poly = pts.map((r) => `${sx(Number(r.time))},${sy(Number(r.mean))}`).join(" ");
    const circles = pts.map((r) => `<circle cx="${sx(Number(r.time))}" cy="${sy(Number(r.mean))}" r="3" fill="${colors[i % colors.length]}"></circle>`).join("");
    return `<polyline points="${poly}" fill="none" stroke="${colors[i % colors.length]}" stroke-width="2"/><g>${circles}</g><text x="46" y="${18 + i * 15}" fill="${colors[i % colors.length]}" font-size="12">${group}</text>`;
  }).join("");
  el.innerHTML = `<svg class="plot-svg" viewBox="0 0 ${width} ${height}"><line x1="${pad}" y1="${height - pad}" x2="${width - pad}" y2="${height - pad}" stroke="#aeb9c8"/><line x1="${pad}" y1="${pad}" x2="${pad}" y2="${height - pad}" stroke="#aeb9c8"/>${series}</svg>`;
}

function plotMetric(metrics) {
  const el = document.querySelector("#metricPlot");
  if (!metrics.length) {
    el.textContent = "No metrics to plot.";
    return;
  }
  const groups = [...new Set(metrics.map((r) => r.condition || r.group || "unlabeled"))];
  const means = groups.map((g) => {
    const vals = metrics.filter((r) => (r.condition || r.group || "unlabeled") === g).map((r) => Number(r.endpoint)).filter(Number.isFinite);
    return vals.reduce((a, b) => a + b, 0) / Math.max(1, vals.length);
  });
  const maxY = Math.max(...means, 1);
  const width = 520, height = 250, pad = 40;
  const barW = (width - pad * 2) / groups.length * 0.65;
  const bars = groups.map((g, i) => {
    const x = pad + i * ((width - pad * 2) / groups.length) + barW * 0.25;
    const h = (means[i] / maxY) * (height - pad * 2);
    return `<rect x="${x}" y="${height - pad - h}" width="${barW}" height="${h}" fill="#2f6fed"></rect><text x="${x + barW / 2}" y="${height - 16}" text-anchor="middle" font-size="11">${g}</text>`;
  }).join("");
  el.innerHTML = `<svg class="plot-svg" viewBox="0 0 ${width} ${height}"><line x1="${pad}" y1="${height - pad}" x2="${width - pad}" y2="${height - pad}" stroke="#aeb9c8"/>${bars}</svg>`;
}

function plotHeatmap(processed) {
  const el = document.querySelector("#heatmapPlot");
  if (!processed.length) {
    el.textContent = "No processed values.";
    return;
  }
  const maxTime = Math.max(...processed.map((r) => Number(r.time)).filter(Number.isFinite));
  const endpoint = processed.filter((r) => Number(r.time) === maxTime);
  const values = endpoint.map((r) => Number(r.analysis_value)).filter(Number.isFinite);
  const minV = Math.min(...values), maxV = Math.max(...values);
  const byWell = new Map(endpoint.map((r) => [r.well, Number(r.analysis_value)]));
  const size = 24, gap = 5, left = 32, top = 24;
  const cells = WELLS.map((well) => {
    const row = ROWS.indexOf(well[0]);
    const col = Number(well.slice(1)) - 1;
    const val = byWell.get(well);
    const t = Number.isFinite(val) ? (val - minV) / Math.max(1e-9, maxV - minV) : 0;
    const fill = Number.isFinite(val) ? `rgb(${230 - t * 150}, ${238 - t * 80}, ${255 - t * 10})` : "#f3f5f8";
    return `<rect x="${left + col * (size + gap)}" y="${top + row * (size + gap)}" width="${size}" height="${size}" rx="5" fill="${fill}" stroke="#d7dee8"><title>${well}: ${val ?? ""}</title></rect>`;
  }).join("");
  el.innerHTML = `<svg class="plot-svg" viewBox="0 0 420 280">${cells}</svg>`;
}

async function parseRawFile() {
  const file = rawFileInput.files[0];
  if (!file) return;
  parseStatus.textContent = "Parsing...";
  setWarnings(parseWarnings, []);
  const form = new FormData();
  form.append("file", file);
  let response;
  let payload;
  try {
    response = await fetchWithTimeout("/api/plate-reader/parse", { method: "POST", body: form }, 30000);
    payload = await readPayload(response);
  } catch (error) {
    parseStatus.textContent = error.name === "AbortError" ? "Parsing timed out after 30 seconds." : "Parse request failed.";
    return;
  }
  if (!response.ok) {
    const messages = errorMessagesFromPayload(payload);
    parseStatus.textContent = messages[0] || "Parse failed";
    setWarnings(parseWarnings, messages);
    return;
  }
  jobId = payload.job_id;
  detectedWells = new Set(payload.detected_wells || []);
  parseStatus.textContent = "Parsed";
  detectedWellCount.textContent = detectedWells.size;
  plateId.textContent = payload.metadata?.plate_id || "-";
  previewRowCount.textContent = payload.preview?.length || 0;
  plateMap = payload.plate_map_template || plateMap;
  setWarnings(parseWarnings, payload.warnings);
  renderTable(previewHead, previewBody, payload.preview || []);
  renderDetectedWellSummary();
  renderPlate();
}

async function analyze() {
  if (!jobId) {
    analysisStatus.textContent = "Parse a file first";
    return;
  }
  const settings = settingsPayload();
  const setupErrors = validateAnalysisSetup(settings);
  setWarnings(qcWarnings, []);
  if (setupErrors.length) {
    analysisStatus.textContent = "Analysis setup needs attention.";
    resultsSection.hidden = false;
    setWarnings(qcWarnings, setupErrors);
    return;
  }

  analysisStatus.textContent = "Analyzing...";
  analyzeButton.disabled = true;
  let response;
  let payload;
  try {
    response = await fetchWithTimeout(`/api/plate-reader/${jobId}/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plate_map: plateMap, settings }),
    }, 45000);
    payload = await readPayload(response);
  } catch (error) {
    analysisStatus.textContent = error.name === "AbortError" ? "Analysis timed out after 45 seconds." : "Analysis request failed.";
    setWarnings(qcWarnings, [analysisStatus.textContent]);
    resultsSection.hidden = false;
    analyzeButton.disabled = false;
    return;
  }
  analyzeButton.disabled = false;
  if (!response.ok) {
    const messages = errorMessagesFromPayload(payload);
    analysisStatus.textContent = messages[0] || "Analysis failed";
    resultsSection.hidden = false;
    setWarnings(qcWarnings, messages);
    return;
  }
  analysisStatus.textContent = "Complete";
  resultsSection.hidden = false;
  latestProcessed = payload.processed_preview || [];
  latestMetrics = payload.metrics_preview || [];
  setWarnings(qcWarnings, payload.warnings);
  addDownloadLinks(payload.downloads);
  renderTable(metricsHead, metricsBody, latestMetrics, 12);
  plotTimecourse(payload.summary_preview || []);
  plotMetric(latestMetrics);
  plotHeatmap(latestProcessed);
}

rawFileInput.addEventListener("change", parseRawFile);
document.querySelector("#applyLabelsButton").addEventListener("click", applyLabels);
document.querySelector("#clearSelectionButton").addEventListener("click", () => {
  selectedWells.clear();
  renderPlate();
  updateSelectionCount();
});
document.querySelector("#downloadMapCsvButton").addEventListener("click", () => downloadText("plate_map.csv", plateMapCsv(), "text/csv"));
document.querySelector("#downloadMapJsonButton").addEventListener("click", () => downloadText("plate_map.json", JSON.stringify(plateMap, null, 2), "application/json"));
document.querySelector("#mapImportInput").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const text = await file.text();
  plateMap = file.name.endsWith(".json") ? JSON.parse(text) : parseCsv(text);
  renderPlate();
});
document.querySelectorAll(".setting-toggle input[type='checkbox']").forEach((checkbox) => {
  checkbox.addEventListener("change", updateSettingStates);
});
plateGrid.addEventListener("pointerdown", startPlateDrag);
plateGrid.addEventListener("pointerover", continuePlateDrag);
window.addEventListener("pointerup", endPlateDrag);
analyzeButton.addEventListener("click", analyze);
renderPlate();
updateSelectionCount();
updateSettingStates();
