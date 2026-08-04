# Data Appendix (Reusable Template)

## A. Scope and versioning
- Project: CiO Phase 0 price-panel foundation.
- Reference panel artifact: `data/processed/panel_v1.0.parquet`.
- Build manifest: `data/processed/panel_manifest.json`.
- Splice audit log: `data/processed/splice_log.csv`.
- Coverage diagnostics: `data/processed/coverage_report.csv`.
- Extended diagnostics bundle: `data/processed/diagnostics/`.

## B. Sources and access

### B1) UBOS Construction Input Price Index (CIPI)
- Source pages:
   - https://www.ubos.org/datasets/ (Excel tables)
   - https://www.ubos.org/?pagename=explore-publications&p_id=104 (press-release archive)
- Frequency: monthly (publication cadence); file layout can change across releases.
- Local raw archive:
  - Harvested releases: `data/raw/ubos_cipi_downloads/`
  - Harvest manifest: `data/raw/ubos_cipi_manifest.csv`
  - Parser inputs for panel build: `data/raw/*.xls*`

### B2) MoFPED Macro Data Portal via `ugatsdb`
- Client: CRAN `ugatsdb` package.
- Pull wrapper: `src/ingest/pull_ugatsdb.R`.
- Output: `data/raw/macro_block.csv` (and parquet if `arrow` is available).
- Failure diagnostics: `data/raw/ugatsdb_failures.csv`.
- Portal instruction alignment: use `Download Data` (dataset + variables + format) or API package per portal API tab.
- Firewall fallback: set environment variable `USE_MANUAL_FALLBACK=TRUE` and place CSV exports in `data/raw/macro_manual/`.

## C. Ingestion and harmonisation pipeline

### C1) Defensive CIPI parse
Script: `src/ingest/parse_cipi.py`
- Detects header row by month-token pattern (not fixed cell coordinates).
- Detects label column by classifiable material/aggregate hits.
- Maps variant labels to stable `series_code` values.
- Emits tidy long panel with provenance fields (`source_file`, `sheet`).

### C2) Vintage splice/rebase handling
Script: `src/index/build_panel.py` (`splice_series()`)
- Overlap-ratio chain-linking by median ratio over overlap months.
- Newest vintage used as scale anchor (`factor=1`).
- Non-overlap pairs flagged and logged (no fabricated links).
- Explicit rebasing history outputs:
   - `data/processed/splice_log.csv` (row-level link factors)
   - `data/processed/diagnostics/rebasing_history_summary.csv` (series-level summary)
   - `data/processed/diagnostics/rebasing_history.md` (flagged NO-OVERLAP review list)

### C3) Macro join
- Macro block is pivoted by `var` and monthly aligned.
- Join key: monthly timestamp at month-start (`MS`).
- Short forward-fill permitted (`limit=2`) to carry quarterly/monthly timing mismatches.

### C4) UBOS CPI/PPI fallback macro build
Script: `src/ingest/build_macro_from_ubos_xlsx.py`
- Extracts `cpi` (headline row) from UBOS CPI Excel tables.
- Extracts `ppi_manufacturing` from UBOS PPI Manufacturing & Utilities tables.
- Writes `data/raw/macro_block.csv` in `date,var,value,source_file` format.

## D. Macro block target variables
- `exchange_rate` (UGX/USD period-average)
- `central_bank_rate` (CBR)
- `lending_rate` (commercial bank lending)
- `cpi` (headline CPI)
- `private_credit` (activity proxy candidate)

## E. Reconciliation protocol (CIPI vs CPI/PPI-Manufacturing)

When overlap exists in the final panel:
1. Construct monthly inflation rates for each index: 
   - Month-on-month: $\Delta\log(I_t)$
   - Year-on-year: $\log(I_t)-\log(I_{t-12})$
2. Compare levels and growth rates over common sample windows.
3. Report:
   - overlap window (`start`, `end`, `n`)
   - correlation of YoY rates
   - median absolute YoY spread
4. Flag sustained divergence episodes for methodological review.

Recommended outputs:
- `data/processed/reconciliation_summary.csv`
- `data/processed/reconciliation_notes.md`

Implemented output in this run:
- `data/processed/reconciliation_report.csv`
- Includes overlap windows and metrics for:
   - CIPI vs CPI
   - CIPI vs PPI-manufacturing

## F. Diagnostics executed (this run)

Script: `src/index/run_diagnostics.py`

Artifacts produced under `data/processed/diagnostics/`:
- `missingness_map.png` — time-by-series missingness map (1 missing, 0 observed).
- `coverage_heatmap.png` — series coverage intensity map.
- `coverage_metrics.csv` — first/last observation, counts, and missingness rates.
- `unit_root_stationarity_tests.csv` — ADF + KPSS in levels and first differences.
- `bai_perron_style_breaks.csv` — dynamic-programming multiple-break scan (Bai-Perron-style segmentation with BIC selection).
- `rebasing_history_summary.csv` and `rebasing_history.md` — explicit splice/rebase history.
- `diagnostics_manifest.json` — machine-readable diagnostics index.

## G. About stationarity/unit-root tests in the MoFPED portal

Short answer: not directly.

The MoFPED Macro Portal + `ugatsdb` provide data access/download APIs. Econometric diagnostics (ADF, KPSS, Bai-Perron, etc.) are not exposed as built-in portal analysis endpoints in the current workflow. Those tests are run downstream in Python/R after data extraction.

## H. Known operational constraints (this run)
- UBOS datasets page provided downloadable Excel files for relevant indices in this run (CIPI/CPI/PPI).
- `ugatsdb` failed due blocked/empty remote DB responses; see `data/raw/ugatsdb_failures.csv`.
- Full macro block (`exchange_rate`, `central_bank_rate`, `lending_rate`, `private_credit`, `activity_indicator`) depends on successful MoFPED/ugatsdb access or fallback extraction.

## I. Reproducibility checklist
- Freeze raw inputs in `data/raw/` (never edit in place).
- Re-run build with `src/index/build_panel.py`.
- Re-run diagnostics with `src/index/run_diagnostics.py`.
- Archive processed outputs and diagnostics as a versioned bundle.
- Cite data DOI/version in downstream papers.
