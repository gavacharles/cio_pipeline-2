# CiO Lab pages

Seven self-contained pages, generated from the pipeline's own artefacts. All follow
the viewer's light/dark setting and carry an Auto / Light / Dark switch, and share
one product shell (`shell.css` and the top bar with the Home · Cost projection ·
Programme · Delay & clauses · Claim builder · Evidence · Data explorer switcher). Open any of
them in any browser: no server, no build tooling, no network needed (Inter, Clash
Grotesk and every library are embedded in the page).

- `app/index.html` — **Home**: what would you like to work on? One card per task,
  and a "continue the claim" strip when a claim is in progress on this device.
- `app/workbench.html` — **Cost projection**: describe the project (type of works,
  contract value, award month, duration, target margin) and read the verdict:
  cost projection with a confidence band and contingency; works-programme
  escalation by phase; a Dynamic Adjustment Mechanism simulator; procurement
  windows. The basket and the model settings sit under "More options".
- `app/programme.html` — **Programme builder**: activities, durations (working
  days) and logic links (FS, SS, FF, SF with lags) in an editable table; a
  critical-path scheduler with a working calendar (5/6/7-day week, public
  holidays) gives early and late dates, total float and the critical path as you
  type; an SVG gantt with links, float, milestones, the Date for Completion and
  the data date; tenability checks (open starts and ends, the Time for
  Completion, activity length, lags, float distribution, progress to the data
  date, sections) and a Sub-Clause 8.3 contents checklist; delay events impacted
  on the programme as fragnets (delaying the start or prolonging the work),
  Employer and Contractor events separately so concurrency shows, with the
  result handed to the delay check and the claim builder; phases by section
  handed to the cost projection; CSV, MS Project XML and JSON export. Road,
  building and water templates.
- `app/claims.html` — **Delay & clauses**: delay and entitlement calculator
  following the SCL Delay and Disruption Protocol (2nd ed., 2017); a notice
  timeline for the selected FIDIC form; a clause explainer with cross-form
  equivalents; the six delay-analysis methods with a fit test; the 22 Core
  Principles. Its figures are offered to the claim builder.
- `app/evidence.html` — **Evidence desk**: drop in letters, instructions and
  minutes (PDF or Word). They are read in the browser with pdf.js and mammoth;
  dates, letter references, clauses cited, subject and sender are pulled out into
  a chronology and an evidence register (Appendix A for the Contractor, B for the
  Engineer, C for the Employer, D for the rest, numbered in date order), with the
  notice deadlines of the selected form marked. Scanned PDFs without a text layer
  are listed but cannot be read. CSV export and a hand-off to the claim builder.
- `app/builder.html` — **Claim builder**: eight steps (contract, event,
  chronology, mitigation, legal basis, delay, quantum, review) drafted into the
  house form of a FIDIC claim: executive summary, project and contract
  particulars, statement of facts with the chronology, mitigation, contractual
  and legal basis, delay analysis, quantum, conclusion and formal request, and
  the appendix index. Every section can be edited in place; a style sweep flags
  dashes, banned vocabulary and gaps left to fill. Export is a Word document in
  Helvetica Neue 11 pt, 1.5 line spacing, decimal numbering linked to the
  headings, table of contents, header and page numbers (`builder_engine.js`
  writes the WordprocessingML directly; JSZip packs it). A worked example loads
  the full Claim No. 1 set of inputs.
- `app/explorer.html` — **Data explorer**: the presentation page. What was
  harvested, how the panel was built and audited, and the current results of the
  P3, P4, P6, P8 and P9 starter models.

Nothing typed or uploaded leaves the browser; state is kept in `localStorage`
(`cio-claim`, `cio-evidence`, `cio-delay`, `cio-programme`, `cio-programme-phases`, `cio-theme`). The hosted copies add
"Redraft with Claude" (claim builder) and "Analyse this document" (evidence desk)
through the artifact runtime; the repo pages work without them.

## Claims library and house style

`app/claims_library.json` holds the FIDIC form register, the causes of delay, the
clause entries and the method table. Clause entries are written from the Red Book
2017 General Conditions; other forms are clause mappings and are labelled
"mapping only" on the page until their text is added. `app/claim_style.json`
holds the house writing style the claim builder drafts in and sweeps against
(voice, fixed formulae, banned punctuation, words and phrases). Edit either JSON
and rebuild.

## How the Workbench forecasts

`build_dashboard.py` estimates a small parameter set per material from
`panel_v1.0.csv` (function `estimate_series`): exponentially weighted drift and
volatility of monthly log-returns (24-month half-life), lag-1 persistence,
calendar-month seasonality, exchange-rate pass-through (OLS on the current and
three lagged shilling returns), the material's actual returns over the 2022
shock, and the average pairwise return correlation used as a common market
factor. The page runs a seeded Monte Carlo over those parameters for the
project's basket. The Method tab shows every parameter. Materials whose panel
history is sparse-filled (coverage under 50% in `coverage_report.csv`) are
excluded from the Workbench.

To replace the statistical model with a trained forecaster, write the same
per-series fields (`mu`, `sigma`, `phi`, `seasonal`, `fx_beta`, `shock_2022`)
from that model into the payload; the page needs no change.

## Regenerating after a pipeline run

```bash
python3 app/build_dashboard.py          # rewrites the seven app/*.html pages
python3 app/build_dashboard.py --cdn --out hosted   # smaller copies loading libraries from cdnjs
python3 app/build_dashboard.py --font Montserrat   # same, set in Montserrat
python3 app/build_dashboard.py --json   # also dumps app/dashboard_data.json for inspection
```

The builder uses only the Python standard library and reads:

| Section | Inputs |
|---|---|
| Overview, foundation | `data/processed/panel_manifest.json`, `coverage_report.csv`, `data/raw/ubos_cipi_manifest.csv`, `data/raw/mofped_bulk/catalog/*.csv`, file counts under `data/raw/` |
| Price explorer | `data/processed/panel_v1.0.csv` |
| Audit trail | `reconciliation_report.csv`, `splice_log.csv`, `diagnostics/*.csv` |
| Research outputs | `p3_clusters.csv`, `p4_spillover_table.csv`, `p4_simi_ranking.csv`, `p6_irf.csv`, `p6_fevd.csv`, `p6_sensitivity_vector.json`, `p8_backtest_results.csv`, `p9_forecast_metrics.csv`; reference baskets are read from `src/estimation/p8_dam_simulator.py` |
| Fiscal context | `data/processed/government_funding_panel.csv` |
| Workbench | `panel_v1.0.csv` (forecast parameters), `coverage_report.csv` (eligibility), P4 ranking for the KPI strip |
| Claims Desk | `app/claims_library.json` |

Nothing under `data/` is modified. Series names shown on the page come from
`SERIES_LABELS` in `build_dashboard.py`; add a line there when a new panel
column appears.

## Files

- `home_template.html`, `explorer_template.html`, `workbench_template.html`,
  `programme_template.html`, `claims_template.html`, `evidence_template.html`,
  `builder_template.html` — one
  template per page (markup, page-specific styles and script).
- `shell.css` — the shared tokens, type, top bar, panels and tables.
- `builder_engine.js` — the claim builder's form, drafting engine and Word writer,
  inlined into `builder.html` at build time.
- `claims_library.json`, `claim_style.json` — the content the claim tools draw on.
- `build_dashboard.py` — reads the artefacts, injects the data, the shell and the
  vendored libraries, rewrites the navigation, and writes the six pages.
- `vendor/echarts.min.js` — Apache ECharts 5.4.3; `vendor/pdf.min.js` and
  `vendor/pdf.worker.min.js` — pdf.js 3.11.174; `vendor/mammoth.browser.min.js` —
  mammoth 1.6.0; `vendor/jszip.min.js` — JSZip 3.10.1. All inlined so the pages
  work offline (`--cdn` loads them from cdnjs instead).
- `vendor/inter.css`, `vendor/montserrat.css` — typefaces (SIL Open Font License, variable weight 400–800) as base64 `@font-face`, inlined so they render offline and inside sandboxed viewers. Inter is the default body face; `--font Montserrat` switches. `vendor/clash-grotesk.css` — Clash Grotesk 300/400/500 (Indian Type Foundry Free Font License, via Fontshare) is the display face for headings and figures.
- `index.html`, `workbench.html`, `programme.html`, `claims.html`, `evidence.html`,
  `builder.html`, `explorer.html` — the generated pages. Commit them alongside data changes so the
  repository always carries pages that match the current artefacts.
