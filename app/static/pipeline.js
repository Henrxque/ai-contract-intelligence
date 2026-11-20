"use strict";
const $ = (id) => document.getElementById(id);
const state = {
  busy: false,
  lineage: null,
  result: null,
  view: "summary",
  runId: null,
  poll: null,
};
const qualityLabels = {
  checks_passed: "Checks passed",
  needs_review: "Needs review",
};
function node(tag, className, text) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text !== undefined) item.textContent = text;
  return item;
}
async function request(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(
      body.error?.message || "The server could not complete this request.",
    );
  }
  return response;
}
function error(message) {
  $("pipeline-error").textContent = message;
  $("pipeline-error").hidden = false;
}
function message(text) {
  $("pipeline-message").textContent = text;
  $("pipeline-message").hidden = false;
}
function busy(value) {
  state.busy = value;
  $("run-demo").disabled = value;
  $("refresh-pipeline").disabled = value;
  for (const control of $("batch-form").querySelectorAll("input,button,select"))
    control.disabled = value;
  for (const button of document.querySelectorAll(".run-actions button"))
    button.disabled = value;
  document
    .querySelector(".runs-section")
    .setAttribute("aria-busy", String(value));
  if (value) state.poll = setInterval(() => refresh().catch(() => {}), 2000);
  else {
    clearInterval(state.poll);
    state.poll = null;
  }
}
function showBatch(report) {
  $("batch-outcome").hidden = false;
  $("batch-title").textContent =
    `${report.processed} attempted · ${report.cached} reused · ${report.failed} failed`;
  $("batch-detail").textContent =
    report.cached === report.items.length
      ? "Every input reused a successful result. No new extraction attempt was created."
      : "Each input has a persisted run and an explicit processing outcome. Inspect the rows below for quality and failure details.";
  $("batch-id").textContent = `Batch ${report.batch_id}`;
}
async function refresh() {
  const summary = await (await request("/api/pipeline/summary")).json();
  $("count-documents").textContent = summary.counts.documents;
  $("count-analyses").textContent = summary.counts.analyses;
  $("count-attempts").textContent =
    `${summary.counts.attempts} recorded processing attempts`;
  $("count-review").textContent = summary.quality.needs_review || 0;
  $("count-fields").textContent = summary.counts.contract_fields;
  $("count-evidence").textContent =
    `${summary.counts.field_evidence} evidence quotes retained`;
  const body = $("runs-body");
  body.replaceChildren();
  if (!summary.recent_runs.length) {
    const row = node("tr");
    const cell = node(
      "td",
      "",
      "No runs yet. Process the fictional batch or upload a batch with persistence consent.",
    );
    cell.colSpan = 5;
    row.append(cell);
    body.append(row);
  }
  for (const run of summary.recent_runs) {
    const row = node("tr");
    const document = node("td");
    document.append(
      node("div", "run-document", run.original_filename),
      node(
        "span",
        "run-meta",
        `${run.run_id.slice(0, 12)} · ${run.mode === "local" ? "Local rules / No LLM" : run.provider_model} · ${run.sample ? "Synthetic" : "Uploaded"}`,
      ),
    );
    const processing = node("td");
    processing.append(node("span", `badge processing-${run.state}`, run.state));
    if (run.error_code)
      processing.append(
        node(
          "span",
          "run-error",
          `${run.error_code}: ${run.error_message || "Inspect the run history."}`,
        ),
      );
    const quality = node("td");
    quality.append(
      run.quality_status
        ? node(
            "span",
            `badge ${run.quality_status}`,
            qualityLabels[run.quality_status],
          )
        : node("span", "run-meta", "Not available"),
    );
    const attempts = node("td", "", `${run.attempt_count} / 3`);
    const actions = node("td");
    const controls = node("div", "run-actions");
    const inspect = node("button", "button button-outline", "Lineage");
    inspect.type = "button";
    inspect.disabled = state.busy;
    inspect.addEventListener("click", () => openLineage(run.run_id));
    controls.append(inspect);
    if (
      run.state !== "succeeded" &&
      (run.attempt_count < 3 || run.state === "running")
    ) {
      const retry = node(
        "button",
        "button button-outline",
        run.state === "failed" ? "Retry" : "Resume",
      );
      retry.type = "button";
      retry.disabled = state.busy;
      retry.addEventListener("click", () => retryRun(run.run_id));
      controls.append(retry);
    }
    actions.append(controls);
    row.append(document, processing, quality, attempts, actions);
    body.append(row);
  }
}
async function batchAction(action) {
  if (state.busy) return;
  $("pipeline-error").hidden = true;
  busy(true);
  message(
    "Processing the batch. Inputs are registered first; results are committed one document at a time. The database counts refresh while processing.",
  );
  try {
    const report = await action();
    showBatch(report);
    await refresh();
    message(
      "Batch finished. Processing states and data-quality outcomes are listed below.",
    );
  } catch (exc) {
    error(exc.message);
    message(
      "The request did not finish successfully. Refresh the run history to inspect any registered inputs before trying again.",
    );
  } finally {
    busy(false);
    await refresh().catch((exc) => error(exc.message));
  }
}
async function retryRun(runId) {
  if (state.busy) return;
  busy(true);
  $("pipeline-error").hidden = true;
  try {
    const outcome = await (
      await request(`/api/pipeline/runs/${runId}/retry`, { method: "POST" })
    ).json();
    message(
      `Run ${outcome.run.state}. Disposition: ${outcome.disposition}. Attempts: ${outcome.run.attempt_count} / 3.`,
    );
  } catch (exc) {
    error(exc.message);
  } finally {
    busy(false);
    await refresh().catch((exc) => error(exc.message));
  }
}
function lineageView(view) {
  state.view = view;
  for (const button of document.querySelectorAll("[data-lineage-view]")) {
    const selected = button.dataset.lineageView === view;
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
  }
  const output =
    view === "summary"
      ? { run: state.lineage.run, attempts: state.lineage.attempts }
      : view === "raw"
        ? state.lineage.staging
        : state.result || {
            message:
              "This run has no committed analysis yet. See run history for the processing failure.",
          };
  $("lineage-output").textContent = JSON.stringify(output, null, 2);
}
async function openLineage(runId) {
  state.runId = runId;
  state.result = null;
  $("export-saved").disabled = true;
  $("lineage-output").textContent = "Loading run lineage…";
  $("lineage-title").textContent = `Run ${runId.slice(0, 12)}`;
  $("lineage-dialog").showModal();
  try {
    state.lineage = await (
      await request(`/api/pipeline/runs/${runId}/lineage`)
    ).json();
    if (state.lineage.run.state === "succeeded")
      state.result = await (
        await request(`/api/pipeline/runs/${runId}/result`)
      ).json();
    $("export-saved").disabled = !state.result;
    lineageView("summary");
  } catch (exc) {
    state.lineage = null;
    $("lineage-output").textContent = exc.message;
  }
}
$("run-demo").addEventListener("click", () =>
  batchAction(async () =>
    (await request("/api/pipeline/demo", { method: "POST" })).json(),
  ),
);
$("batch-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const files = [...$("batch-files").files];
  if (!files.length || files.length > 10) {
    error("Choose between 1 and 10 PDF files.");
    return;
  }
  if (files.reduce((total, file) => total + file.size, 0) > 10 * 1024 * 1024) {
    error("The combined batch must be at most 10 MB.");
    return;
  }
  if (!$("persist-consent").checked) {
    error("Persistence consent is required for batch mode.");
    return;
  }
  const mode = $("batch-mode").value;
  if (mode === "openai" && !$("provider-consent").checked) {
    error("Confirm the document-text transmission to OpenAI.");
    return;
  }
  const form = new FormData();
  for (const file of files) form.append("files", file);
  form.append("mode", mode);
  form.append("persist_consent", "true");
  form.append("provider_consent", String($("provider-consent").checked));
  batchAction(async () =>
    (
      await request("/api/pipeline/batches", { method: "POST", body: form })
    ).json(),
  );
});
$("batch-mode").addEventListener("change", () => {
  $("provider-consent-row").hidden = $("batch-mode").value !== "openai";
  $("provider-consent").required = $("batch-mode").value === "openai";
});
$("refresh-pipeline").addEventListener("click", () =>
  refresh().catch((exc) => error(exc.message)),
);
$("close-lineage").addEventListener("click", () => $("lineage-dialog").close());
for (const button of document.querySelectorAll("[data-lineage-view]"))
  button.addEventListener("click", () => {
    if (state.lineage) lineageView(button.dataset.lineageView);
  });
document.querySelector(".lineage-tabs").addEventListener("keydown", (event) => {
  if (!state.lineage) return;
  const views = ["summary", "raw", "result"];
  const index = views.indexOf(state.view);
  const next =
    event.key === "ArrowRight"
      ? (index + 1) % 3
      : event.key === "ArrowLeft"
        ? (index + 2) % 3
        : event.key === "Home"
          ? 0
          : event.key === "End"
            ? 2
            : -1;
  if (next >= 0) {
    event.preventDefault();
    lineageView(views[next]);
    document.querySelector(`[data-lineage-view="${views[next]}"]`).focus();
  }
});
$("export-saved").addEventListener("click", async () => {
  if (!state.result) return;
  $("export-saved").disabled = true;
  try {
    const format = $("saved-export-format").value;
    const response = await request(`/api/export/${format}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(state.result),
    });
    const url = URL.createObjectURL(await response.blob());
    const link = node("a");
    link.href = url;
    link.download = `contract-analysis.${format}`;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
  } catch (exc) {
    $("lineage-output").textContent = exc.message;
  } finally {
    $("export-saved").disabled = !state.result;
  }
});
request("/api/health")
  .then((response) => response.json())
  .then((health) => {
    $("openai-option").disabled = !health.ai_available;
    $("openai-option").textContent = health.ai_available
      ? `OpenAI · ${health.ai_model}`
      : "OpenAI · Not configured";
  })
  .catch((exc) => error(exc.message));
refresh().catch((exc) => error(exc.message));
