# CiO dashboard pages

Two self-contained pages, generated from the pipeline's own artefacts. Open
either in any browser — no server, no build tooling, no network needed (fonts
fall back to the system sans if offline).

- `app/index.html` — **Phase 0 Explorer**: the presentation page. What was
  harvested, how the panel was built and audited, and the current results of the
  P3, P4, P6, P8 and P9 starter models.
- `app/workbench.html` — **Projection Workbench**: the working tool. A user
  describes a project (template or custom input basket, contract value, award
  month, duration, spend profile) and gets, live in the browser:
  cost projection with a confidence band and contingency; works-programme
  escalation by phase; a Dynamic Adjustment Mechanism simulator (forecast paths
  or historical replay); and procurement-window recommendations.

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
python3 app/build_dashboard.py          # rewrites app/index.html
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

Nothing under `data/` is modified. Series names shown on the page come from
`SERIES_LABELS` in `build_dashboard.py`; add a line there when a new panel
column appears.

## Files

- `template.html` — Explorer markup, styles and chart code (ECharts).
- `workbench_template.html` — Workbench markup, styles, simulation engine and tools.
- `build_dashboard.py` — reads the artefacts, injects the data and the vendored
  chart library, writes `index.html`.
- `vendor/echarts.min.js` — Apache ECharts 5.4.3, inlined so the page works offline.
- `index.html`, `workbench.html` — the generated pages. Commit them alongside
  data changes so the repository always carries pages that match the current artefacts.
