# MoFPED Portal Export Checklist

Use this when `ugatsdb` is installed but API DB connection is blocked.
Portal: https://mepd.finance.go.ug/apps/macro-data-portal/

## 1) Export required series from Download Data tab
For each item below:
- Select dataset
- Select target variable/series
- Set date filter from 2016-01-01 (or earliest available)
- Format: CSV
- Download

Target files (save into data/raw/macro_manual/):

1. exchange_rate.csv
   - target: UGX/USD period-average (BoU exchange series)
2. central_bank_rate.csv
   - target: CBR (central bank rate)
3. lending_rate.csv
   - target: commercial lending rate
4. cpi.csv
   - target: headline CPI
5. private_credit.csv
   - target: private sector credit (total)

Optional:
6. activity_indicator.csv
   - target: IOP or another monthly activity proxy

## 2) Build macro block from exported files
Run:
python src/ingest/build_macro_from_mofped_csv.py --manual-dir data/raw/macro_manual --out data/raw/macro_block.csv

## 3) Build full panel
Run:
python src/index/build_panel.py --raw data/raw --out data/processed
python src/index/reconcile_cipi.py --panel data/processed/panel_v1.0.parquet --out data/processed/reconciliation_report.csv

## 4) Validate
Run:
pytest -q

## Notes
- The parser infers variable mapping from filename keywords. Keep names close to the list above.
- If a file is skipped, review data/raw/macro_manual_skipped.txt.
