MoFPED Macro Portal manual export drop-folder
=============================================

If `ugatsdb` cannot connect to the portal database from your network,
export CSV files directly from:
https://mepd.finance.go.ug/apps/macro-data-portal/

Required series (one CSV each; filename should include keyword):
- exchange_rate      (keyword: exchange or usd)
- central_bank_rate  (keyword: cbr)
- lending_rate       (keyword: lending)
- cpi                (keyword: cpi)
- private_credit     (keyword: credit or psc)

After saving CSV files in this folder, run:
python src/ingest/build_macro_from_mofped_csv.py --manual-dir data/raw/macro_manual --out data/raw/macro_block.csv

Then rebuild panel:
python src/index/build_panel.py --raw data/raw --out data/processed
python src/index/reconcile_cipi.py --panel data/processed/panel_v1.0.parquet --out data/processed/reconciliation_report.csv
