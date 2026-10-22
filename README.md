# CiO Price-Panel Pipeline (Phase 0)

The single data foundation for the seven-paper portfolio. Two obtainable public
sources only: the **UBOS Construction Input Price Index** (monthly Excel tables,
2016–present, material-disaggregated) and the **MoFPED Macro Data Portal** via
the **`ugatsdb`** R API.

## Quick start
```bash
pip install -r requirements.txt          # Python deps
Rscript -e "install.packages('ugatsdb')" # R API client
# optional: bulk-harvest UBOS CIPI release files (pdf/xlsx as published)
python src/ingest/pull_ubos_cipi.py --out data/raw/ubos_cipi_downloads
# optional: bulk-download MOFPED datasets/catalog via ugatsdb (GitHub pattern)
Rscript src/ingest/pull_mofped_portal_bulk.R data/raw/mofped_bulk
# optional: derive macro block from MOFPED bulk dataset CSVs
python src/ingest/build_macro_from_mofped_csv.py --manual-dir data/raw/mofped_bulk/datasets --out data/raw/macro_block.csv
# optional: build CPI/PPI fallback macro block from UBOS Excel tables
python src/ingest/build_macro_from_ubos_xlsx.py --ubos-dir data/raw/ubos_cipi_downloads --out data/raw/macro_block.csv
# if MoFPED API is blocked, export CSVs from portal to data/raw/macro_manual/
python src/ingest/build_macro_from_mofped_csv.py --manual-dir data/raw/macro_manual --out data/raw/macro_block.csv
# see docs/MOFPED_EXPORT_CHECKLIST.md for exact portal export steps
# global 2015-2026 source registry + API pull attempt (MOFPED/BoU/UBOS/IMF/WB/ILO/Comtrade)
python src/ingest/pull_global_catalog.py --config config/global_series_2015_2026.json
# put UBOS CIPI .xlsx files in data/raw/ (parser consumes .xls/.xlsx only)
./run_phase0.sh
```

## Layout
```
src/ingest/parse_cipi.py     defensive UBOS CIPI Excel parser (layout-robust)
src/ingest/pull_ubos_cipi.py UBOS CIPI release harvester + manifest
src/ingest/build_macro_from_ubos_xlsx.py UBOS CPI/PPI -> macro_block fallback
src/ingest/build_macro_from_mofped_csv.py MoFPED portal CSV -> macro_block fallback
src/ingest/pull_mofped_portal_bulk.R MOFPED catalog + dataset bulk CSV dump via ugatsdb
src/ingest/pull_ugatsdb.R    macro-block puller (firewall fallback documented)
src/ingest/pull_global_catalog.py source/dataset/series registry + multi-source API pull
src/index/build_panel.py     splice vintages + join macro + diagnostics -> panel_v1.0
src/index/reconcile_cipi.py  CIPI-vs-CPI/PPI overlap diagnostics
tests/test_pipeline.py       pytest regression suite (parser + splicer)
src/market/                  construction-cost forecasting market (play money): country
                             config, first-print settlement, nowcast, LMSR, ledger, CLI
tests/test_market.py         market tests (settlement, LMSR, ledger, config)
src/forecast/                structural CIPI forecaster: recovers UBOS's weights, forecasts the
                             29 components from macro drivers, re-aggregates (docs/FORECAST_MODEL.md)
tests/test_forecast.py       forecaster tests (exact rebuild, no look-ahead, coherence, scenarios)
config/forecast_model.yaml   driver groups, shrinkage, simulation and scenarios
config/policy_events.yaml    sourced tax measures (fuel, cement, paint excise) applied as known shocks
src/ingest/build_rainfall_block.py  monthly rainfall driver (ERA5, five towns) -> data/raw/
src/ingest/build_weekly_drivers.py  weekly Brent + UGX/KES/RWF readings for the weekly note
src/ingest/pull_knbs_cipi.py, parse_knbs_cipi.py  Kenya KNBS quarterly CIPI PDFs
src/forecast/weekly_note.py  weekly construction-cost notes per country (data/processed/notes/)
src/forecast/quarterly_model.py  Kenya quarterly forecaster (KNBS indices)
src/ingest/build_fx_history.py  IMF monthly KES/RWF/UGX per USD
src/webapp/app.py            participant app: invites, contracts, price reports, note, leaderboard
src/market/cycle.py          daily/weekly automation (deploy/crontab.example); see docs/OPERATIONS.md
config/series_map.yaml       editable dataset/series codes
config/countries/*.yaml      per-country market config (Uganda pilot, Kenya planned)
config/global_series_2015_2026.json quoted 2015-2026 source/dataset/series catalog
data/raw/                    inputs (CIPI xlsx + macro pulls) — frozen, never edited
data/processed/              panel_v1.0.{parquet,csv}, splice_log.csv, coverage_report.csv,
                             panel_manifest.json, reconciliation_report.csv
                             (the full audit trail)
```

## Outputs every paper consumes
- `panel_v1.0.parquet` — wide material-by-month index matrix + macro block
- `splice_log.csv` — every rebasing splice factor (P1 methodology requires this)
- `reconciliation_report.csv` — CIPI vs CPI/PPI overlap diagnostics
- `coverage_report.csv` / `panel_manifest.json` — provenance & missingness

## Forecasting market
`docs/MARKET_DESIGN.md` covers the contract rules, legal position, backtest and how to add a
country. Quick start: `python src/market/run_market.py backtest`, then `open`, `board`, `settle`.

Deposit `data/processed/` to Zenodo and cite the version DOI in every paper.
