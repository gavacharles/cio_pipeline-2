# CiO Phase 0 Explorer

A single-page, self-contained presentation of the Phase 0 pipeline: what was
harvested, how the panel was built and audited, and the current results of the
P3, P4, P6, P8 and P9 starter models.

Open `app/index.html` in any browser — no server, no build tooling, no network
needed (fonts fall back to the system sans if offline).

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

Nothing under `data/` is modified. Series names shown on the page come from
`SERIES_LABELS` in `build_dashboard.py`; add a line there when a new panel
column appears.

## Files

- `template.html` — page markup, styles and chart code (ECharts).
- `build_dashboard.py` — reads the artefacts, injects the data and the vendored
  chart library, writes `index.html`.
- `vendor/echarts.min.js` — Apache ECharts 5.4.3, inlined so the page works offline.
- `index.html` — the generated page. Commit it alongside data changes so the
  repository always carries a page that matches the current artefacts.
