#!/usr/bin/env bash
# One-command Phase 0 build.
set -euo pipefail

PYTHON_BIN="python3"
if [[ -x ".venv/bin/python" ]]; then
  PYTHON_BIN=".venv/bin/python"
fi

echo "[0/4] Harvesting UBOS CIPI releases..."
"$PYTHON_BIN" src/ingest/pull_ubos_cipi.py --out data/raw/ubos_cipi_downloads || \
  echo "  UBOS harvest failed — check connectivity or run later."
echo "[1/4] Pulling macro block from MoFPED portal (ugatsdb)..."
if ! Rscript src/ingest/pull_ugatsdb.R 2016-01-01 data/raw; then
  echo "  ugatsdb pull failed — trying MOFPED bulk downloader pattern from GitHub repo"
  Rscript src/ingest/pull_mofped_portal_bulk.R data/raw/mofped_bulk || true
  "$PYTHON_BIN" src/ingest/build_macro_from_mofped_csv.py --manual-dir data/raw/mofped_bulk/datasets --out data/raw/macro_block.csv || \
  "$PYTHON_BIN" src/ingest/build_macro_from_mofped_csv.py --manual-dir data/raw/macro_manual --out data/raw/macro_block.csv || \
  "$PYTHON_BIN" src/ingest/build_macro_from_ubos_xlsx.py --ubos-dir data/raw/ubos_cipi_downloads --out data/raw/macro_block.csv || true
fi
echo "[2/4] Building panel_v1.0 (parse + splice + join + diagnose)..."
"$PYTHON_BIN" src/index/build_panel.py --raw data/raw --out data/processed
echo "[3/4] Running tests..."
"$PYTHON_BIN" -m pytest tests -q
echo "Done. Panel at data/processed/panel_v1.0.parquet ; audit trail in data/processed/"
