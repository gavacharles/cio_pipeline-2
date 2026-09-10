# CiO dashboard pages

Three self-contained pages, generated from the pipeline's own artefacts. All follow
the viewer's light/dark setting and carry an Auto / Light / Dark switch, and share
one product shell (top bar with the Explorer · Workbench · Claims Desk switcher). Open
either in any browser — no server, no build tooling, no network needed (Inter is
embedded in the page).

- `app/index.html` — **Phase 0 Explorer**: the presentation page. What was
  harvested, how the panel was built and audited, and the current results of the
  P3, P4, P6, P8 and P9 starter models.
- `app/workbench.html` — **Projection Workbench**: the working tool. A user
  describes a project (template or custom input basket, contract value, award
  month, duration, spend profile) and gets, live in the browser:
  cost projection with a confidence band and contingency; works-programme
  escalation by phase; a Dynamic Adjustment Mechanism simulator (forecast paths
  or historical replay); and procurement-window recommendations.
- `app/claims.html` — **Claims Desk**: delay and entitlement calculator following
  the SCL Delay and Disruption Protocol (2nd ed., 2017) — EOT net of float,
  concurrency handled per Core Principles 10 and 14, prolongation cost, Emden and
  Eichleay overhead formulae; a notice timeline for the selected FIDIC form
  (28 / 84 / 42 + 42 days for the 2017 family, 28 / 42 / 42 for 1999 and the MDB
  editions); a clause explainer with cross-form equivalents; the Protocol's six
  delay-analysis methods with a fit test; and the 22 Core Principles.

## Claims library

`app/claims_library.json` holds the FIDIC form register, the causes of delay, the
clause entries and the method table. Clause entries are written from the Red Book
2017 General Conditions; other forms are clause mappings and are labelled
"mapping only" on the page until their text is added. Edit the JSON and rebuild.

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
python3 app/build_dashboard.py          # rewrites app/index.html and app/workbench.html
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

- `template.html` — Explorer markup, styles and chart code (ECharts).
- `workbench_template.html` — Workbench markup, styles, simulation engine and tools.
- `claims_template.html` — Claims Desk markup, styles and calculator; `claims_library.json` is its content.
- `build_dashboard.py` — reads the artefacts, injects the data and the vendored
  chart library, writes `index.html`.
- `vendor/echarts.min.js` — Apache ECharts 5.4.3, inlined so the page works offline.
- `vendor/inter.css`, `vendor/montserrat.css` — typefaces (SIL Open Font License, variable weight 400–800) as base64 `@font-face`, inlined so they render offline and inside sandboxed viewers. Inter is the default body face; `--font Montserrat` switches. `vendor/clash-grotesk.css` — Clash Grotesk 300/400/500 (Indian Type Foundry Free Font License, via Fontshare) is the display face for headings and figures.
- `index.html`, `workbench.html`, `claims.html` — the generated pages. Commit them alongside
  data changes so the repository always carries pages that match the current artefacts.
