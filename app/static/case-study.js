"use strict";
const stages = {
  ingestion: [
    "Ingest once, identify by content.",
    "PDF bytes are hashed with SHA-256. A run also records the extraction mode, model, pipeline version and policy fingerprint. Repeated submissions reuse successful results for that configuration.",
    "documents · runs · batch_items",
  ],
  extraction: [
    "Keep raw extraction separate from normalized output.",
    "The PDF reader preserves page numbers. Labelled-field rules work offline; the optional OpenAI adapter requests typed output. Page text and extractor fields are checkpointed before quality checks.",
    "extraction_staging · app/analysis.py",
  ],
  validation: [
    "An extracted value still has to earn its status.",
    "Required fields, calendar dates, amounts, currencies, date order and source quotes are checked deterministically. Missing values stay null. Ambiguous or unsupported values remain visible for review.",
    "app/validation.py · review_findings",
  ],
  storage: [
    "Commit the whole result, or leave it uncommitted.",
    "Analysis, fields, evidence, findings and completion state are written in one SQLite transaction. The accepted-data view excludes contracts that require review. Failed jobs keep their operational history.",
    "contract_fields · field_evidence · quality_quarantine",
  ],
  delivery: [
    "Give people usable data and the context to judge it.",
    "Query accepted fields or quarantine, inspect run attempts and raw staging, review a contract's source evidence, and export the full result as JSON, CSV or Excel.",
    "app/cli.py · /pipeline · /api/export",
  ],
};
for (const button of document.querySelectorAll("[data-stage]")) {
  button.addEventListener("click", () => {
    for (const other of document.querySelectorAll("[data-stage]")) {
      other.classList.toggle("selected", other === button);
      other.setAttribute("aria-pressed", String(other === button));
    }
    const [title, description, code] = stages[button.dataset.stage];
    document.getElementById("stage-title").textContent = title;
    document.getElementById("stage-description").textContent = description;
    document.getElementById("stage-code").textContent = code;
  });
}
function metric(id, countId, value) {
  document.getElementById(id).textContent =
    value.rate === null ? "Not measured" : `${(value.rate * 100).toFixed(1)}%`;
  document.getElementById(countId).textContent =
    `${value.numerator} / ${value.denominator} annotated fields`;
}
fetch("/api/evaluation")
  .then(async (response) => {
    if (!response.ok)
      throw new Error("No measured evaluation report is available.");
    return response.json();
  })
  .then((report) => {
    document.getElementById("evaluation-context").textContent =
      `${report.mode === "local" ? "Local rule-based extraction; no LLM" : "LLM extraction"} · ${report.document_count} synthetic documents · ${report.field_count} annotated fields · Dataset ${report.dataset_id}`;
    metric(
      "metric-exact",
      "metric-exact-count",
      report.metrics.value_exact_match,
    );
    metric(
      "metric-recall",
      "metric-recall-count",
      report.metrics.non_null_value_recall,
    );
    document.getElementById("metric-false").textContent =
      report.metrics.false_supported_fields;
    document.getElementById("metric-mode").textContent =
      report.mode === "local" ? "None" : report.model;
    document.getElementById("metric-mode-note").textContent =
      report.mode === "local"
        ? "No provider request; cost is not reported"
        : "Provider usage disclosed in report JSON";
    for (const doc of report.documents) {
      const misses = doc.fields.filter((field) => !field.value_match);
      if (!misses.length) continue;
      const article = document.createElement("article");
      const heading = document.createElement("h3");
      heading.textContent = doc.filename;
      const detail = document.createElement("p");
      detail.textContent = `${misses.length} field value ${misses.length === 1 ? "mismatch" : "mismatches"}. ${misses.map((f) => `${f.field}: ${f.actual_status}`).join("; ")}. Full expected and actual values are retained in the report.`;
      article.append(heading, detail);
      document.getElementById("benchmark-failures").append(article);
    }
  })
  .catch((error) => {
    document.getElementById("evaluation-context").textContent = error.message;
  });
