# CiO Phase 0 Implementation Report (End-to-End)

Date: 2026-07-22  
Workspace: cio_pipeline-2

## 1) Executive summary

This project started from a partially scaffolded Phase 0 pipeline and reached a complete, auditable, reproducible data foundation for downstream papers (P1, P3, P4, P6, P8, P9).

By the end:
- A harmonized material-by-month panel is built and versioned.
- A macro block is integrated (exchange rate, CBR/central bank rate, lending rate, inflation, activity indicator), plus private credit and PPI-manufacturing for reconciliation.
- CIPI was reconciled against CPI and PPI-manufacturing in overlap windows.
- Diagnostics are generated (coverage, missingness, structural breaks, unit-root/stationarity, rebasing history).
- Estimation starter scripts run end-to-end and tests pass.

Final core artifact:
- data/processed/panel_v1.0.parquet
- data/processed/panel_v1.0.xlsx

## 2) Initial state and objectives

### Initial state
The repository already contained:
- Ingestion/parsing scaffolding for UBOS and MOFPED access.
- Panel builder and tests.
- Estimation templates for P3/P4/P6/P8/P9.

### Target objectives
The requested outcomes were:
1. Pull UBOS CIPI monthly Excel history and parse robustly.
2. Install and use `ugatsdb` for MOFPED macro portal data.
3. Build a harmonized material-by-month panel with macro block.
4. Reconcile CIPI with CPI and PPI-manufacturing where overlap exists.
5. Produce reproducible diagnostics and documentation for paper-ready use.

## 3) Data-source implementation and acquisition path

### 3.1 UBOS CIPI/CPI/PPI acquisition
A downloader was implemented and hardened to harvest UBOS dataset Excel releases with manifest logging.

Key result:
- UBOS release files downloaded into data/raw/ubos_cipi_downloads/
- Manifest produced: data/raw/ubos_cipi_manifest.csv

### 3.2 MOFPED macro portal via `ugatsdb`
The official route was used via R `ugatsdb`.

Actions taken:
- `ugatsdb` installation and repeated connectivity tests.
- Wrapper hardening for TLS peer-verification environment and reconnect behavior.
- Enhanced failure logging into ugatsdb failure outputs.

### 3.3 GitHub pattern integration for MOFPED bulk extraction
To strengthen MOFPED extraction, the workflow from:
- https://github.com/gavacharles/mofped-macrodata-api-downloader
was integrated into the project via a bulk downloader script.

Added script:
- src/ingest/pull_mofped_portal_bulk.R

This produced:
- data/raw/mofped_bulk/catalog/*.csv
- data/raw/mofped_bulk/datasets/*.csv
- data/raw/mofped_bulk/download_log.csv

### 3.4 Fallback strategy and schema harmonization
Because source behavior can vary by environment/network and output shape:
- A macro CSV harmonizer/ingestor was implemented and expanded:
  - src/ingest/build_macro_from_mofped_csv.py
- Explicit column mappings were added for wide bulk datasets (e.g., BOU_E, BOU_MMI, BOU_I, BOU_CPI, BOU_PSC).
- UBOS CPI/PPI extraction fallback script was added:
  - src/ingest/build_macro_from_ubos_xlsx.py

Result: robust macro block generation under multiple source-output scenarios.

## 4) Parsing and harmonization engineering

### 4.1 CIPI parser hardening
The parser was adapted to handle evolving UBOS table layouts, including datetime-like month headers.

Key file:
- src/ingest/parse_cipi.py

### 4.2 Parse-failure root cause and fix
At one point, parse failures appeared because non-CIPI workbooks (CPI/PPI/RPPI) were being unintentionally swept into the CIPI parser path.

Fixes:
- Ingestion discovery changed to recursive search with filtering and deduplication.
- CIPI-only inclusion rule enforced in panel builder.
- Stale parse failure file behavior fixed (removed when no active failures).

Key file:
- src/index/build_panel.py

Outcome:
- Active CIPI parse failures resolved for target CIPI ingestion.

### 4.3 Rebasing/vintage splicing
The panel builder chain-links vintages by overlap-ratio (median on overlap months), anchors on newest scale, and explicitly flags non-overlap links.

Artifacts:
- data/processed/splice_log.csv
- data/processed/diagnostics/rebasing_history_summary.csv
- data/processed/diagnostics/rebasing_history.md

This provides an explicit audit trail of rebasing history and manual-review flags.

## 5) Panel build, macro integration, and reconciliation

### 5.1 Panel construction
Pipeline logic:
1. Parse CIPI workbooks.
2. Stack long-format observations.
3. Splice vintages by overlap-ratio chain-linking.
4. Pivot to wide monthly material matrix.
5. Join macro block by monthly timestamp.
6. Emit diagnostics and manifests.

Main builder:
- src/index/build_panel.py

### 5.2 Macro variables in final panel
Final panel includes:
- `exchange_rate`
- `central_bank_rate`
- `lending_rate`
- `cpi`
- `activity_indicator`
- `private_credit`
- `ppi_manufacturing` (for reconciliation use)

### 5.3 Reconciliation completed
CIPI reconciliation was run against CPI and PPI-manufacturing over overlap windows.

Output:
- data/processed/reconciliation_report.csv

Current status from report:
- CIPI vs CPI: ok
- CIPI vs PPI-manufacturing: ok

## 6) Diagnostics package delivered

A dedicated diagnostics runner was implemented:
- src/index/run_diagnostics.py

Generated under:
- data/processed/diagnostics/

Files:
- coverage_heatmap.png
- missingness_map.png
- coverage_metrics.csv
- bai_perron_style_breaks.csv
- unit_root_stationarity_tests.csv
- rebasing_history_summary.csv
- rebasing_history.md
- diagnostics_manifest.json

### 6.1 Unit-root/stationarity tests
Implemented with ADF and KPSS at level and first-difference.

Result summary (current run):
- difference_stationary: 20 series
- level_stationary: 1 series
- mixed_or_inconclusive: 2 series
- insufficient_sample: 6 series

Interpretation: most usable series are difference-stationary; sparse series remain structurally short.

### 6.2 Structural-break scans
Bai-Perron-style multiple-break scans were produced using dynamic programming segmentation + BIC-based break-count selection.

Output:
- data/processed/diagnostics/bai_perron_style_breaks.csv

## 7) Estimation-stage readiness validation

Estimation template runs were executed after panel stabilization:
- P3 clustering
- P4 spillover/SIMI
- P6 SVAR
- P8 DAM simulation
- P9 walk-forward forecasting

Generated outputs include:
- p3_clusters.csv
- p4_spillover_table.csv
- p4_simi_ranking.csv
- p4_network.graphml
- p6_irf.csv
- p6_fevd.csv
- p6_sensitivity_vector.json
- p8_backtest_results.csv
- p9_forecast_metrics.csv

Regression suite:
- tests/test_pipeline.py
- Result: 10 passed

## 8) Final data quality and maturity status

From panel manifest:
- panel_version: 1.0
- shape: 106 months × 29 series
- date window: 2017-07-01 to 2026-04-01
- overall missingness: 20.33%

Interpretation:
- The panel is production-ready for paper estimation.
- Missingness is mostly structural for short-history series, not parser failure.
- For model-specific use, balanced subsets or transformation rules should be selected per methodology (already supported by diagnostics).

## 9) Key code and process improvements delivered

1. MOFPED bulk acquisition capability added and integrated.
2. `run_phase0.sh` improved to use workspace virtualenv Python automatically.
3. CIPI parser robustness improved for layout/header drift.
4. Panel builder improved for recursive discovery, filtering, deduplication, and stale failure cleanup.
5. Diagnostics framework added for coverage/missingness/stationarity/breaks/rebasing.
6. Documentation updated with methodology and operational notes.

## 10) MOFPED portal analytics note

Question addressed: Are unit-root/stationarity tests available directly in MOFPED portal?

Answer:
- Not in this implemented workflow.
- The portal/API (`ugatsdb`) is used for data retrieval.
- Econometric diagnostics (ADF/KPSS/Bai-Perron-style scans) are run downstream in Python.

## 11) Reproducibility and audit trail

Core reproducibility artifacts:
- data/processed/panel_v1.0.parquet
- data/processed/panel_v1.0.xlsx
- data/processed/panel_manifest.json
- data/processed/splice_log.csv
- data/processed/reconciliation_report.csv
- data/processed/diagnostics/diagnostics_manifest.json

Supporting documentation:
- docs/DATA_APPENDIX.md
- docs/MOFPED_EXPORT_CHECKLIST.md
- docs/GLOBAL_DATA_CATALOG_2015_2026.md

## 12) Conclusion

The Phase 0 objective is complete and operationally robust:
- harmonized panel built,
- macro block integrated,
- CIPI reconciled against CPI/PPI overlap,
- rebasing history explicitly documented,
- diagnostics generated,
- tests and estimation starters validated.

The dataset is ready for paper production with normal model-specific handling of structural sparsity and stationarity transformations.
