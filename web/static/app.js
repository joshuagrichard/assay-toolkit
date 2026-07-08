let tools = [];
let activeTool = null;
let reviewItems = [];
let activeReviewMode = "overlay";

const TOOL_NAV_LABELS = {
  scratch_wound: "Scratch Assay Analyzer",
};

const toolList = document.querySelector("#toolList");
const toolName = document.querySelector("#toolName");
const toolDescription = document.querySelector("#toolDescription");
const acceptedTypes = document.querySelector("#acceptedTypes");
const paramsForm = document.querySelector("#paramsForm");
const fileInput = document.querySelector("#fileInput");
const folderInput = document.querySelector("#folderInput");
const selectedFileCount = document.querySelector("#selectedFileCount");
const runButton = document.querySelector("#runButton");
const statusBox = document.querySelector("#status");
const downloads = document.querySelector("#downloads");
const summary = document.querySelector("#summary");
const summaryCards = document.querySelector("#summaryCards");
const metadataPreview = document.querySelector("#metadataPreview");
const metadataPreviewCount = document.querySelector("#metadataPreviewCount");
const metadataPreviewBody = document.querySelector("#metadataPreviewBody");
const analysisSection = document.querySelector("#analysisSection");
const resultsTableBody = document.querySelector("#resultsTableBody");
const closurePlot = document.querySelector("#closurePlot");
const reviewSection = document.querySelector("#reviewSection");
const reviewGrid = document.querySelector("#reviewGrid");
const reviewCount = document.querySelector("#reviewCount");
const reviewFilter = document.querySelector("#reviewFilter");
const modeButtons = Array.from(document.querySelectorAll(".mode-button"));

function setStatus(message) {
  statusBox.textContent = message;
}

function setSelectedFileCount() {
  const count = getSelectedFiles().length;
  selectedFileCount.textContent = count === 1 ? "1 file selected" : `${count} files selected`;
}

function getSelectedFiles() {
  return [
    ...Array.from(fileInput.files || []),
    ...Array.from(folderInput.files || []),
  ];
}

function displayPath(file) {
  return file.webkitRelativePath || file.name;
}

async function readResponsePayload(response) {
  const text = await response.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    return { detail: text };
  }
}

function addDownloadLink(href, text) {
  const link = document.createElement("a");
  link.href = href;
  link.textContent = text;
  downloads.appendChild(link);
  return link;
}

function formatMetric(value, suffix = "") {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "";
  return `${Number(value).toFixed(2)}${suffix}`;
}

function formatInteger(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "";
  return Math.round(Number(value)).toLocaleString();
}

function parseFilenameMetadata(filename) {
  const normalized = filename.replace(/\\/g, "/");
  const parts = normalized.split("/").filter(Boolean);
  const basename = parts.length ? parts[parts.length - 1] : normalized;
  const folderParts = parts.slice(0, -1);
  const stem = basename.replace(/\.[^.]+$/, "").replace(/\s+copy(?:\s+\d+)?$/i, "").trim();
  const meta = {
    filename: normalized,
    time_value: null,
    time_raw: "",
    condition_id: "",
    well_id: "",
    field_id: "",
    group_id: stem,
  };
  const timeMatch = stem.match(/\b(\d+)\s*(hrs|hr|hours|hour|h)(?=$|[^A-Za-z0-9])/i);
  if (timeMatch) {
    meta.time_raw = timeMatch[0];
    meta.time_value = Number.parseInt(timeMatch[1], 10);
  }
  folderParts.forEach((part) => {
    if (meta.time_value !== null) return;
    const folderTime = part.match(/\b(\d+)\s*(hrs|hr|hours|hour|h)(?=$|[^A-Za-z0-9])/i);
    if (folderTime) {
      meta.time_raw = folderTime[0];
      meta.time_value = Number.parseInt(folderTime[1], 10);
    }
  });
  const conditionParts = folderParts
    .filter((part) => !/\b(\d+)\s*(hrs|hr|hours|hour|h)(?=$|[^A-Za-z0-9])/i.test(part))
    .map((part) => part.trim().replace(/[_\-\s]+/g, "_").replace(/^_+|_+$/g, ""))
    .filter(Boolean)
    .filter((part) => !["images", "image", "scratch", "scratch_assay", "scratch_assays", "wound", "wound_healing", "timepoint", "time_point"].includes(part.toLowerCase()));
  if (conditionParts.length) {
    meta.condition_id = conditionParts.join("_");
  }
  const fieldMatch = stem.match(/(^|[^A-Za-z0-9])([A-H]\d{2}f\d{2}d\d+)($|[^A-Za-z0-9])/i);
  if (fieldMatch) {
    meta.field_id = fieldMatch[2].toUpperCase();
    const well = meta.field_id.match(/^([A-H])(\d{2})/i);
    if (well) meta.well_id = `${well[1].toUpperCase()}${Number.parseInt(well[2], 10)}`;
  }
  const withoutTime = stem.replace(/\b(\d+)\s*(hrs|hr|hours|hour|h)(?=$|[^A-Za-z0-9])/ig, "");
  const explicitWell = withoutTime.match(/\b([A-H])0?(\d{1,2})\b/i);
  if (explicitWell && !meta.well_id) {
    meta.well_id = `${explicitWell[1].toUpperCase()}${Number.parseInt(explicitWell[2], 10)}`;
  }
  meta.group_id = stem
    .replace(/\b(\d+)\s*(hrs|hr|hours|hour|h)(?=$|[^A-Za-z0-9])/ig, "")
    .replace(/(^|[^A-Za-z0-9])([A-H]\d{2}f\d{2}d\d+)($|[^A-Za-z0-9])/ig, "$1$3")
    .replace(/\bcopy(?:\s+\d+)?\b/ig, "")
    .replace(/[_\-\s]+/g, "_")
    .replace(/^_+|_+$/g, "");
  if (!meta.group_id) meta.group_id = stem;
  if (meta.condition_id) {
    const genericFileGroups = new Set(["image", "img", "field", "scan", "tile", "well"]);
    meta.group_id = meta.group_id && meta.group_id !== stem && !genericFileGroups.has(meta.group_id.toLowerCase())
      ? `${meta.condition_id}_${meta.group_id}`
      : meta.condition_id;
  }
  return meta;
}

function renderMetadataPreview() {
  const files = getSelectedFiles();
  setSelectedFileCount();
  metadataPreview.hidden = files.length === 0;
  metadataPreviewBody.innerHTML = "";
  metadataPreviewCount.textContent = `${files.length} selected files`;
  files.map((file) => parseFilenameMetadata(displayPath(file))).forEach((meta) => {
    const row = document.createElement("tr");
    [
      meta.filename,
      meta.time_value === null ? "" : `${meta.time_value}h`,
      meta.condition_id,
      meta.well_id,
      meta.field_id,
      meta.group_id,
    ].forEach((value) => {
      const cell = document.createElement("td");
      cell.textContent = value || "";
      row.appendChild(cell);
    });
    metadataPreviewBody.appendChild(row);
  });
}

function renderSummaryCards(data) {
  summaryCards.innerHTML = "";
  if (!data || Object.keys(data).length === 0) return;
  const cards = [
    ["Images", data.images_analyzed],
    ["Successful", data.successful_images],
    ["Failed", data.failed_images],
    ["Median closure", data.median_percent_closure === undefined ? null : `${Number(data.median_percent_closure).toFixed(2)}%`],
  ];
  cards.forEach(([label, value]) => {
    if (value === null || value === undefined || value === "") return;
    const card = document.createElement("div");
    card.className = "summary-card";
    const labelNode = document.createElement("span");
    labelNode.textContent = label;
    const valueNode = document.createElement("strong");
    valueNode.textContent = value;
    card.appendChild(labelNode);
    card.appendChild(valueNode);
    summaryCards.appendChild(card);
  });
}

function itemKey(item) {
  return item.filename;
}

function setItemQc(item, qcStatus) {
  item.qc_status = qcStatus;
  renderResultsTable();
  renderReviewGallery();
  updateQcDownload();
}

function itemMatchesFilter(item, query) {
  if (!query) return true;
  const haystack = [
    item.filename,
    item.well_id,
    item.field_id,
    item.group_id,
    item.condition_id,
    item.time_value,
    item.qc_status,
    item.selected_wound_geometry,
  ].filter(Boolean).join(" ").toLowerCase();
  return haystack.includes(query.toLowerCase());
}

function setReviewMode(mode) {
  activeReviewMode = mode;
  modeButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.mode === mode);
  });
  renderReviewGallery();
}

function qcButtons(item) {
  const wrap = document.createElement("div");
  wrap.className = "qc-buttons";
  ["accept", "flag", "exclude"].forEach((status) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `qc-button ${item.qc_status === status ? "active" : ""}`;
    button.dataset.status = status;
    button.textContent = status[0].toUpperCase() + status.slice(1);
    button.addEventListener("click", () => setItemQc(item, status));
    wrap.appendChild(button);
  });
  return wrap;
}

function renderReviewGallery() {
  const query = reviewFilter.value.trim();
  const visibleItems = reviewItems.filter((item) => itemMatchesFilter(item, query));
  reviewSection.hidden = reviewItems.length === 0;
  reviewGrid.innerHTML = "";
  reviewCount.textContent = `${visibleItems.length} of ${reviewItems.length} images`;

  visibleItems.forEach((item) => {
    const card = document.createElement("article");
    card.id = `review-${CSS.escape(itemKey(item))}`;
    card.className = `review-card ${item.error ? "failed" : ""} qc-${item.qc_status || "accept"}`;

    const imageWrap = document.createElement("a");
    imageWrap.className = "review-image";
    const imageUrl = item.images[activeReviewMode] || item.images.overlay || item.images.debug || item.images.mask || item.images.source;
    if (imageUrl) {
      imageWrap.href = imageUrl;
      imageWrap.target = "_blank";
      imageWrap.rel = "noopener";
      const img = document.createElement("img");
      img.src = imageUrl;
      img.alt = `${activeReviewMode} for ${item.filename}`;
      imageWrap.appendChild(img);
    } else {
      imageWrap.textContent = "No preview";
    }

    const body = document.createElement("div");
    body.className = "review-body";

    const title = document.createElement("h3");
    title.textContent = item.filename;
    body.appendChild(title);
    body.appendChild(qcButtons(item));

    const meta = document.createElement("div");
    meta.className = "review-meta";
    [
      ["Time", item.time_value === null || item.time_value === undefined ? "" : `${item.time_value}h`],
      ["Condition", item.condition_id || ""],
      ["Well", item.well_id || ""],
      ["Field", item.field_id || ""],
      ["Geometry", item.selected_wound_geometry || ""],
      ["Closure", formatMetric(item.percent_closure, "%")],
      ["Open area", formatInteger(item.open_area_px)],
    ].forEach(([label, value]) => {
      if (!value) return;
      const pill = document.createElement("span");
      pill.textContent = `${label}: ${value}`;
      meta.appendChild(pill);
    });
    body.appendChild(meta);

    if (item.error) {
      const error = document.createElement("p");
      error.className = "review-error";
      error.textContent = item.error;
      body.appendChild(error);
    }

    card.appendChild(imageWrap);
    card.appendChild(body);
    reviewGrid.appendChild(card);
  });
}

function renderResultsTable() {
  analysisSection.hidden = reviewItems.length === 0;
  resultsTableBody.innerHTML = "";
  reviewItems.forEach((item) => {
    const row = document.createElement("tr");
    row.className = `qc-${item.qc_status || "accept"}`;
    row.addEventListener("click", () => {
      const card = document.getElementById(`review-${CSS.escape(itemKey(item))}`);
      if (card) card.scrollIntoView({ behavior: "smooth", block: "center" });
    });

    const qcCell = document.createElement("td");
    qcCell.appendChild(qcButtons(item));
    row.appendChild(qcCell);

    [
      item.filename,
      item.time_value === null || item.time_value === undefined ? "" : `${item.time_value}h`,
      item.condition_id || "",
      item.well_id || "",
      item.field_id || "",
      item.selected_wound_geometry || "",
      formatInteger(item.open_area_px),
      formatMetric(item.percent_closure, "%"),
      item.error ? "Failed" : "OK",
    ].forEach((value) => {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.appendChild(cell);
    });
    resultsTableBody.appendChild(row);
  });
  renderClosurePlot();
}

function renderClosurePlot() {
  const plotted = reviewItems
    .filter((item) => !item.error && item.qc_status !== "exclude")
    .filter((item) => item.time_value !== null && item.time_value !== undefined)
    .filter((item) => item.percent_closure !== null && item.percent_closure !== undefined && !Number.isNaN(Number(item.percent_closure)));

  if (!plotted.length) {
    closurePlot.textContent = "No QC-included closure values to plot.";
    return;
  }

  const width = 760;
  const height = 260;
  const pad = 42;
  const times = plotted.map((item) => Number(item.time_value));
  const closures = plotted.map((item) => Number(item.percent_closure));
  const minTime = Math.min(...times);
  const maxTime = Math.max(...times);
  const maxClosure = Math.max(100, ...closures);
  const xScale = (time) => pad + ((time - minTime) / Math.max(1, maxTime - minTime)) * (width - pad * 2);
  const yScale = (closure) => height - pad - (closure / maxClosure) * (height - pad * 2);
  const byGroup = new Map();
  plotted.forEach((item) => {
    const group = item.group_id || item.well_id || "Group";
    if (!byGroup.has(group)) byGroup.set(group, []);
    byGroup.get(group).push(item);
  });
  const colors = ["#2f6fed", "#7c5cc4", "#1f8a99", "#b56b1d", "#6b7787", "#b54762"];

  const series = Array.from(byGroup.entries()).map(([group, items], index) => {
    const color = colors[index % colors.length];
    const points = items
      .slice()
      .sort((a, b) => Number(a.time_value) - Number(b.time_value))
      .map((item) => `${xScale(Number(item.time_value)).toFixed(1)},${yScale(Number(item.percent_closure)).toFixed(1)}`)
      .join(" ");
    const circles = items.map((item) => (
      `<circle cx="${xScale(Number(item.time_value)).toFixed(1)}" cy="${yScale(Number(item.percent_closure)).toFixed(1)}" r="4" fill="${color}"><title>${item.filename}: ${formatMetric(item.percent_closure, "%")}</title></circle>`
    )).join("");
    return `<polyline points="${points}" fill="none" stroke="${color}" stroke-width="2"/><g>${circles}</g><text x="${pad}" y="${18 + index * 16}" fill="${color}" font-size="12">${group}</text>`;
  }).join("");

  closurePlot.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Percent closure over time">
      <line x1="${pad}" y1="${height - pad}" x2="${width - pad}" y2="${height - pad}" stroke="#aeb9c8"/>
      <line x1="${pad}" y1="${pad}" x2="${pad}" y2="${height - pad}" stroke="#aeb9c8"/>
      <text x="${width / 2}" y="${height - 8}" text-anchor="middle" font-size="12" fill="#647386">Time (h)</text>
      <text x="14" y="${height / 2}" text-anchor="middle" transform="rotate(-90 14 ${height / 2})" font-size="12" fill="#647386">Closure (%)</text>
      <text x="${pad - 8}" y="${height - pad + 4}" text-anchor="end" font-size="11" fill="#647386">0</text>
      <text x="${pad - 8}" y="${yScale(100).toFixed(1)}" text-anchor="end" font-size="11" fill="#647386">100</text>
      <text x="${pad}" y="${height - pad + 18}" text-anchor="middle" font-size="11" fill="#647386">${minTime}</text>
      <text x="${width - pad}" y="${height - pad + 18}" text-anchor="middle" font-size="11" fill="#647386">${maxTime}</text>
      ${series}
    </svg>
  `;
}

function csvEscape(value) {
  const text = value === null || value === undefined ? "" : String(value);
  return `"${text.replace(/"/g, '""')}"`;
}

function reviewedCsv() {
  const columns = [
    "qc_status",
    "filename",
    "time_value",
    "condition_id",
    "well_id",
    "field_id",
    "group_id",
    "selected_wound_geometry",
    "t0_geometry_score",
    "open_area_px",
    "percent_closure",
    "error",
  ];
  const lines = [columns.join(",")];
  reviewItems.forEach((item) => {
    lines.push(columns.map((column) => csvEscape(item[column])).join(","));
  });
  return lines.join("\n");
}

function updateQcDownload() {
  const existing = document.querySelector("#qcCsvDownload");
  if (existing) {
    URL.revokeObjectURL(existing.href);
    existing.remove();
  }
  if (!reviewItems.length) return;
  const blob = new Blob([reviewedCsv()], { type: "text/csv" });
  const link = addDownloadLink(URL.createObjectURL(blob), "Download reviewed CSV");
  link.id = "qcCsvDownload";
  link.download = "scratch_results_reviewed.csv";
}

function renderTools() {
  toolList.innerHTML = "";
  tools.forEach((tool) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `tool-button ${activeTool && activeTool.id === tool.id ? "active" : ""}`;
    button.textContent = TOOL_NAV_LABELS[tool.id] || tool.name;
    button.addEventListener("click", () => selectTool(tool.id));
    toolList.appendChild(button);
  });
}

function renderParameters() {
  paramsForm.innerHTML = "";
  activeTool.parameters.forEach((param) => {
    const label = document.createElement("label");
    label.textContent = param.label;

    let field;
    if (param.kind === "choice") {
      field = document.createElement("select");
      param.choices.forEach((choice) => {
        const option = document.createElement("option");
        option.value = choice;
        option.textContent = choice;
        field.appendChild(option);
      });
    } else {
      field = document.createElement("input");
      field.type = param.kind === "float" || param.kind === "int" ? "number" : "text";
      if (param.kind === "float") field.step = "0.01";
      if (param.kind === "int") field.step = "1";
      if (param.minimum !== null) field.min = param.minimum;
      if (param.maximum !== null) field.max = param.maximum;
    }
    field.name = param.name;
    field.value = param.default;
    label.appendChild(field);
    paramsForm.appendChild(label);
  });
}

function selectTool(toolId) {
  activeTool = tools.find((tool) => tool.id === toolId);
  toolName.textContent = activeTool.name;
  toolDescription.textContent = activeTool.description;
  acceptedTypes.textContent = `Accepted: ${activeTool.accepted_extensions.join(", ")}`;
  renderTools();
  renderParameters();
}

function collectParams() {
  const params = {};
  activeTool.parameters.forEach((param) => {
    const field = paramsForm.elements[param.name];
    if (!field) return;
    if (param.kind === "int") {
      params[param.name] = Number.parseInt(field.value, 10);
    } else if (param.kind === "float") {
      params[param.name] = Number.parseFloat(field.value);
    } else {
      params[param.name] = field.value;
    }
  });
  return params;
}

async function runAnalysis() {
  if (!activeTool) return;
  const selectedFiles = getSelectedFiles();
  if (!selectedFiles.length) {
    setStatus("Select one or more assay image files first.");
    return;
  }

  runButton.disabled = true;
  downloads.innerHTML = "";
  summary.textContent = "";
  summaryCards.innerHTML = "";
  reviewItems = [];
  renderResultsTable();
  renderReviewGallery();
  setStatus("Uploading files and running analysis...");

  const form = new FormData();
  form.append("params_json", JSON.stringify(collectParams()));
  selectedFiles.forEach((file) => form.append("files", file, displayPath(file)));

  try {
    const response = await fetch(`/api/tools/${encodeURIComponent(activeTool.id)}/jobs`, {
      method: "POST",
      body: form,
    });
    const payload = await readResponsePayload(response);
    if (!response.ok) throw new Error(payload.detail || "Analysis failed");

    setStatus(`Analysis complete. Job ${payload.job_id}`);
    summary.textContent = JSON.stringify(payload.summary, null, 2);
    renderSummaryCards(payload.summary);
    reviewItems = Array.isArray(payload.review_items)
      ? payload.review_items.map((item) => ({ ...item, qc_status: item.error ? "flag" : "accept" }))
      : [];
    renderResultsTable();
    renderReviewGallery();
    if (payload.results_csv_url) {
      addDownloadLink(payload.results_csv_url, "Download raw CSV");
    }
    if (payload.artifacts_zip_url) {
      addDownloadLink(payload.artifacts_zip_url, "Download artifacts ZIP");
    }
    updateQcDownload();
  } catch (error) {
    setStatus(error && error.message ? error.message : "Analysis failed.");
  } finally {
    runButton.disabled = false;
  }
}

async function boot() {
  const response = await fetch("/api/tools");
  const payload = await readResponsePayload(response);
  if (!response.ok) throw new Error(payload.detail || "Could not load assay tools.");
  tools = payload;
  if (tools.length) {
    selectTool(tools[0].id);
  } else {
    toolName.textContent = "No tools registered";
  }
}

fileInput.addEventListener("change", renderMetadataPreview);
folderInput.addEventListener("change", renderMetadataPreview);
setSelectedFileCount();
runButton.addEventListener("click", runAnalysis);
reviewFilter.addEventListener("input", renderReviewGallery);
modeButtons.forEach((button) => {
  button.addEventListener("click", () => setReviewMode(button.dataset.mode));
});
boot().catch((error) => setStatus(error.message));
