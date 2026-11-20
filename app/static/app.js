"use strict";
const $ = (id) => document.getElementById(id);
const state = {
  file: null,
  mode: "local",
  result: null,
  busy: false,
  selected: null,
  page: 0,
  view: "fields",
  timer: null,
};
const statusLabels = {
  supported: "Supported",
  missing: "Missing",
  uncertain: "Uncertain",
  invalid: "Invalid",
  checks_passed: "Checks passed",
  needs_review: "Needs review",
};
const labels = {
  empty_file: "Empty document",
  invalid_pdf: "This isn't a PDF",
  ocr_required: "OCR needed",
  encrypted_pdf: "Password-protected PDF",
  ai_not_configured: "LLM setup needed",
  ai_timeout: "Extraction timed out",
  file_too_large: "File too large",
};

function element(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
}
function badge(status) {
  return element("span", `badge ${status}`, statusLabels[status] || status);
}
function toast(message) {
  $("toast").textContent = message;
  $("toast").hidden = false;
  clearTimeout(state.timer);
  state.timer = setTimeout(() => {
    $("toast").hidden = true;
  }, 3500);
}
function showError(code, message) {
  $("error-title").textContent =
    labels[code] || "Unable to complete this action";
  $("error-message").textContent = message;
  $("error-banner").hidden = false;
}
async function api(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const error = new Error(
      body.error?.message ||
        "The server could not complete the request. Please try again.",
    );
    error.code = body.error?.code || "server_error";
    throw error;
  }
  return response;
}
function updateUploadButton() {
  $("analyze-upload").disabled =
    state.busy ||
    !state.file ||
    (state.mode === "openai" && !$("ai-consent").checked);
}
function setBusy(busy) {
  state.busy = busy;
  $("loading").hidden = !busy;
  $("sample-button").disabled = busy;
  $("sample-select").disabled = busy;
  $("file-input").disabled = busy;
  $("mode-local").disabled = busy;
  $("mode-ai").disabled = busy || $("mode-ai").dataset.available !== "true";
  $("export-button").disabled = busy;
  $("results").setAttribute("aria-busy", String(busy));
  updateUploadButton();
}
function chooseFile(file) {
  if (state.busy || !file) return;
  $("error-banner").hidden = true;
  state.file = null;
  if (!file.name.toLowerCase().endsWith(".pdf")) {
    showError(
      "invalid_pdf",
      "Choose a PDF document. Other file types are not supported.",
    );
  } else if (file.size > 10 * 1024 * 1024) {
    showError("file_too_large", "Choose a PDF smaller than 10 MB.");
  } else {
    state.file = file;
  }
  $("chosen-file").textContent = state.file
    ? `${file.name} · ${(file.size / 1024).toFixed(1)} KB`
    : "No file selected";
  updateUploadButton();
}
function setMode(mode) {
  state.mode = mode;
  for (const key of ["local", "ai"]) {
    const selected = (key === "local" ? "local" : "openai") === mode;
    $("mode-" + key).classList.toggle("selected", selected);
    $("mode-" + key).setAttribute("aria-pressed", String(selected));
  }
  $("ai-consent-row").hidden = mode !== "openai";
  $("mode-description").textContent =
    mode === "openai"
      ? "Uses OpenAI for varied contract formats. Sends extracted document text to the provider."
      : "Reads labeled fields in English and Portuguese. Runs locally; no AI provider.";
  updateUploadButton();
}
async function runAnalysis(kind) {
  if (state.busy) return;
  $("error-banner").hidden = true;
  setBusy(true);
  $("loading-title").textContent =
    kind === "upload" && state.mode === "openai"
      ? "Extracting with the language model…"
      : "Reading and checking the document…";
  try {
    let response;
    if (kind === "sample") {
      response = await api("/api/demo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sample: $("sample-select").value }),
      });
    } else {
      const form = new FormData();
      form.append("file", state.file);
      form.append("mode", state.mode);
      response = await api("/api/analyze", { method: "POST", body: form });
    }
    state.result = await response.json();
    state.page = 0;
    renderResult();
    $("results").scrollIntoView({
      behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "instant"
        : "smooth",
      block: "start",
    });
    toast("Analysis ready. Inspect the fields and source evidence.");
  } catch (error) {
    showError(
      error.code || "connection_error",
      error.message === "Failed to fetch"
        ? "Cannot reach the local server. Make sure the application is running."
        : error.message,
    );
  } finally {
    setBusy(false);
  }
}
function renderResult() {
  const result = state.result;
  $("empty-state").hidden = true;
  $("results").hidden = false;
  $("result-filename").textContent = result.filename;
  $("result-meta").textContent =
    `${result.page_count} ${result.page_count === 1 ? "page" : "pages"} · ${result.mode === "local" ? "Local rules · No LLM" : result.provider_model} · ${result.sample ? "Synthetic sample · " : ""}${result.elapsed_ms.toLocaleString()} ms`;
  $("result-status").className = `badge ${result.status}`;
  $("result-status").textContent = statusLabels[result.status];
  const attention = result.fields.filter(
    (f) =>
      ["uncertain", "invalid"].includes(f.status) ||
      (f.required && f.status === "missing"),
  );
  $("stat-extracted").replaceChildren(
    document.createTextNode(
      String(result.fields.filter((f) => f.value !== null).length),
    ),
    element("small", "", `/ ${result.fields.length}`),
  );
  $("stat-supported").textContent = result.fields.filter(
    (f) => f.status === "supported",
  ).length;
  $("stat-attention").textContent = attention.length;
  $("stat-missing").textContent = result.fields.filter(
    (f) => f.status === "missing",
  ).length;
  $("review-count").textContent = result.findings.length;
  $("fields-list").replaceChildren();
  let currentGroup = null;
  for (const field of result.fields) {
    if (currentGroup !== field.group) {
      $("fields-list").append(element("div", "group-heading", field.group));
      currentGroup = field.group;
    }
    const row = element("button", "field-row");
    row.dataset.key = field.key;
    row.type = "button";
    row.setAttribute("aria-pressed", "false");
    row.setAttribute(
      "aria-label",
      `${field.label}: ${field.value || "Not found"}. ${statusLabels[field.status]}. View evidence.`,
    );
    const label = element("span", "field-label", field.label);
    if (field.required) {
      const mark = element("span", "required-mark", "*");
      mark.title = "Required by the extraction policy";
      label.append(mark);
    }
    row.append(
      label,
      element(
        "span",
        `field-value${field.value === null ? " empty" : ""}`,
        field.key === "total_value" && field.status === "supported"
          ? formatAmount(field.value, result)
          : field.value || "Not found",
      ),
      badge(field.status),
    );
    row.addEventListener("click", () => selectField(field.key));
    $("fields-list").append(row);
  }
  $("findings-list").replaceChildren();
  if (!result.findings.length)
    $("findings-list").append(
      element(
        "p",
        "review-clear",
        "No findings from the configured checks. Review the source before relying on the output.",
      ),
    );
  for (const finding of result.findings) {
    const field = result.fields.find((f) => f.key === finding.field);
    const card = element("button", "finding-card");
    card.type = "button";
    const title = element("h4", "", field?.label || finding.field);
    title.append(badge(field?.status || "uncertain"));
    card.append(
      title,
      element("p", "", finding.message),
      element(
        "span",
        "finding-code",
        `${finding.severity.toUpperCase()} / ${finding.code}`,
      ),
    );
    card.addEventListener("click", () => selectField(finding.field));
    $("findings-list").append(card);
  }
  $("json-output").textContent = JSON.stringify(result, null, 2);
  $("result-notices").replaceChildren(
    ...result.notices.map((notice) => element("p", "", notice)),
  );
  setView("fields");
  selectField(attention[0]?.key || result.fields[0].key);
  renderPage();
}
function formatAmount(value, result) {
  const currency = result.fields.find(
    (f) => f.key === "currency" && f.status === "supported",
  )?.value;
  const amount = Number(value);
  return Number.isFinite(amount)
    ? `${currency ? currency + " " : ""}${amount.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : value;
}
function selectField(key) {
  state.selected = key;
  const field = state.result.fields.find((f) => f.key === key);
  for (const row of document.querySelectorAll(".field-row")) {
    const selected = row.dataset.key === key;
    row.classList.toggle("selected", selected);
    row.setAttribute("aria-pressed", String(selected));
  }
  const container = $("evidence-content");
  container.replaceChildren(
    element("div", "evidence-field-name", field.label),
    element("p", "evidence-value", field.value || "No explicit value found"),
    badge(field.status),
  );
  if (!field.evidence.length) {
    container.append(
      element(
        "p",
        "evidence-placeholder",
        "No source quote was extracted for this field. Check the original contract before adding a value.",
      ),
    );
  } else {
    for (const evidence of field.evidence) {
      container.append(
        element("blockquote", "evidence-quote", evidence.quote),
        element("p", "evidence-page", `Source · Page ${evidence.page}`),
      );
    }
    const index = state.result.pages.findIndex(
      (page) => page.number === field.evidence[0].page,
    );
    if (index >= 0) state.page = index;
    renderPage();
  }
  for (const issue of field.issues)
    container.append(element("p", "evidence-issue", issue));
  container.append(
    element(
      "p",
      "evidence-info",
      field.required
        ? "Required by the extraction policy. Source checks confirm text correspondence; they do not replace human review."
        : "Optional under the extraction policy. Missing optional clauses remain visible in the exported data.",
    ),
  );
}
function renderPage() {
  if (!state.result) return;
  const page = state.result.pages[state.page];
  $("page-indicator").textContent =
    `Page ${page.number} / ${state.result.page_count}`;
  $("source-text").textContent =
    page.text || "No text layer found on this page.";
  $("prev-page").disabled = state.page === 0;
  $("next-page").disabled = state.page >= state.result.pages.length - 1;
}
function setView(view) {
  state.view = view;
  for (const name of ["fields", "review", "json"]) {
    const selected = name === view;
    $("tab-" + name).classList.toggle("active", selected);
    $("tab-" + name).setAttribute("aria-selected", String(selected));
    $("tab-" + name).tabIndex = selected ? 0 : -1;
    $("panel-" + name).hidden = !selected;
  }
}
$("file-input").addEventListener("change", (event) =>
  chooseFile(event.target.files[0]),
);
for (const name of ["dragenter", "dragover"])
  $("dropzone").addEventListener(name, (event) => {
    event.preventDefault();
    if (!state.busy) $("dropzone").classList.add("dragover");
  });
for (const name of ["dragleave", "drop"])
  $("dropzone").addEventListener(name, (event) => {
    event.preventDefault();
    $("dropzone").classList.remove("dragover");
  });
$("dropzone").addEventListener("drop", (event) =>
  chooseFile(event.dataTransfer.files[0]),
);
$("analyze-upload").addEventListener("click", () => {
  if (!$("analyze-upload").disabled) runAnalysis("upload");
});
$("sample-button").addEventListener("click", () => runAnalysis("sample"));
$("sample-select").addEventListener("change", () => {
  $("sample-download").href = "/api/samples/" + $("sample-select").value;
});
$("mode-local").addEventListener("click", () => setMode("local"));
$("mode-ai").addEventListener("click", () => setMode("openai"));
$("ai-consent").addEventListener("change", updateUploadButton);
$("dismiss-error").addEventListener("click", () => {
  $("error-banner").hidden = true;
});
for (const view of ["fields", "review", "json"])
  $("tab-" + view).addEventListener("click", () => setView(view));
document.querySelector(".tabs").addEventListener("keydown", (event) => {
  const tabs = ["fields", "review", "json"];
  const index = tabs.indexOf(state.view);
  const next =
    event.key === "ArrowRight"
      ? (index + 1) % tabs.length
      : event.key === "ArrowLeft"
        ? (index + tabs.length - 1) % tabs.length
        : event.key === "Home"
          ? 0
          : event.key === "End"
            ? tabs.length - 1
            : -1;
  if (next >= 0) {
    event.preventDefault();
    setView(tabs[next]);
    $("tab-" + tabs[next]).focus();
  }
});
$("prev-page").addEventListener("click", () => {
  state.page = Math.max(0, state.page - 1);
  renderPage();
});
$("next-page").addEventListener("click", () => {
  state.page = Math.min(state.result.pages.length - 1, state.page + 1);
  renderPage();
});
$("copy-json").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(JSON.stringify(state.result, null, 2));
    toast("JSON copied to clipboard.");
  } catch {
    toast("Clipboard unavailable. Use Export to download the JSON file.");
  }
});
$("export-button").addEventListener("click", async () => {
  $("export-button").disabled = true;
  try {
    const format = $("export-format").value;
    const response = await api("/api/export/" + format, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(state.result),
    });
    const url = URL.createObjectURL(await response.blob());
    const link = element("a");
    link.href = url;
    link.download = `contract-analysis.${format}`;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
    toast(
      `${format.toUpperCase()} export downloaded with review statuses and source evidence.`,
    );
  } catch (error) {
    showError(error.code || "export_failed", error.message);
  } finally {
    $("export-button").disabled = state.busy;
  }
});
$("about-button").addEventListener("click", () =>
  $("about-dialog").showModal(),
);
$("close-about").addEventListener("click", () => $("about-dialog").close());
$("about-dialog").addEventListener("click", (event) => {
  if (event.target === $("about-dialog")) {
    const bounds = $("about-dialog").getBoundingClientRect();
    if (
      event.clientX < bounds.left ||
      event.clientX > bounds.right ||
      event.clientY < bounds.top ||
      event.clientY > bounds.bottom
    )
      $("about-dialog").close();
  }
});
api("/api/health")
  .then((response) => response.json())
  .then((health) => {
    $("mode-ai").dataset.available = String(health.ai_available);
    $("mode-ai").disabled = !health.ai_available;
    $("ai-tag").textContent = health.ai_available
      ? health.ai_model
      : "Not configured";
  })
  .catch(() =>
    showError(
      "connection_error",
      "Cannot reach the application server. Start the server and refresh this page.",
    ),
  );
