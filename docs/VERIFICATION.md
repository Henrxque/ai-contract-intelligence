# Verification record

Verified locally on 2026-11-20, Windows, Python 3.14.3.

## Automated

- `python -m pytest -q`: 86 tests passed.
- `python -m pip check`: no broken requirements.
- `node --check` on the individual-review, case-study and pipeline scripts: JavaScript syntax passed.
- The v0.2.0 wheel built successfully and contains 15 runtime modules, 12 frontend assets, eight PDFs, the SQL schema and both benchmark JSON files.
- Eight checked-in PDFs pass through the evaluation engine; the original three remain available in the individual-review demo.
- JSON/CSV/Excel round trips preserve values, missing fields, review statuses and evidence.
- Formula-like spreadsheet inputs are escaped, including leading whitespace.
- Oversized Excel cells and unsupported control characters return actionable errors instead of silently truncating or dropping data.
- A local field exceeding the evidence length limit returns an actionable error.
- Input tests include invalid signatures, broken PDFs, encryption, textless pages, mixed text/blank pages, page limits and file-size limits.
- Provider tests simulate typed success, refusal, timeout, authentication failure, quota failure and invalid output.
- Reported provider token usage is preserved in a mocked test; monetary cost is not inferred.
- Database tests verify normalized output, quarantine, replay/cache identity, concurrent registration/claims, expired-worker fencing, bounded retries, raw-stage retention, interrupted-batch recovery and transaction rollback.
- A SQLite backup is reopened and compared with its source in an automated round trip.
- CLI batch execution works from a directory outside the repository when the package is installed.
- The evaluation detects changed fixture hashes, incomplete values, missing predictions and fabricated evidence; zero denominators return unknown rather than a fabricated score.

## Reproducible pipeline artifacts

- [First CLI batch](pipeline-first-run.json): eight attempts, zero cache hits and zero processing failures.
- [Repeated CLI batch](pipeline-replay.json): zero attempts and eight cache hits.
- [Database summary](pipeline-summary.json): eight documents/runs/attempts/analyses, 88 fields, 77 evidence quotes and 21 findings; two contracts pass checks and six need review.
- [Local evaluation](../app/benchmark/local-report.json): 76/88 exact value matches; 74/86 non-null recall; eleven missed fields in narrative prose and one incomplete wrapped clause. This is a synthetic development baseline using local rules, not live LLM accuracy.

The installed Starlette version emits a deprecation warning for its HTTPX test transport. Tests still pass; this warning does not indicate a failed application request.

## Manual browser verification

- Uploaded the actual Meridian PDF through the browser file chooser: eleven fields, checks passed.
- Downloaded the Excel export through the browser and reopened it with openpyxl: eleven fields and all three expected sheets.
- Inspected Northstar's missing fields, ambiguous payment terms, page evidence, review queue and structured JSON view.
- Checked the layout at a 390 × 844 viewport: no horizontal overflow; restored the default desktop viewport afterward.
- Opened the local API reference and checked browser console logs: no errors were reported during the inspected flow.
- Captured [the full workspace](workspace.jpg), [the review queue](review.jpg) and [the mobile layout](mobile.jpg).
- Opened the new case study and exercised its architecture-stage controls. Its metrics matched the checked-in baseline report.
- Processed the three-contract batch through the browser: 33 fields, three successful processing runs, one passing contract and two requiring review.
- Repeated that batch: zero new attempts, three reused runs and unchanged normalized output.
- Inspected raw staging (`48,000.00`) and normalized output (`48000.00`), retained null end date, and downloaded/reopened the saved Excel result with all review states preserved.
- Uploaded a deliberately invalid fictional PDF: processing failed without partial normalized output; explicitly retrying recorded the second failed attempt while completed analyses remained at three.
- Checked the case-study and pipeline layouts at 390 × 844. The page fits the viewport; the wide run table scrolls inside its wrapper.
- Captured [case study](case-study.jpg), [pipeline](pipeline.jpg), [case study on mobile](case-study-mobile.jpg) and [pipeline on mobile](pipeline-mobile.jpg).
- Restored the desktop viewport after responsive checks; case-study and pipeline browser logs reported no errors or warnings during the inspected flows.

## Not verified

- Live paid OpenAI extraction: no configured provider key was used.
- Extraction accuracy on real-world contract datasets: not measured.
- Docker build: Docker is not available in the checked environment.
- GitHub-hosted CI: workflow configured, not run before repository publication.
- Public deployment, production load, hostile-PDF isolation and multiuser security: outside this local portfolio version.
