#!/usr/bin/env python3
"""
build_global_oil_block.py
==========================
Fold the global Brent crude oil price series into the CiO panel as an
auxiliary macro node.

MoFPED's Macro Data Portal (https://mepd.finance.go.ug/apps/macro-data-portal/)
and the `ugatsdb` catalog (see docs/GLOBAL_DATA_CATALOG_2015_2026.md) do not
carry a global oil benchmark series -- MoFPED's external-sector tables cover
exchange rates, BoP and trade, but not commodity benchmark prices. Brent is
therefore sourced from FRED series POILBREUSDM (IMF Primary Commodity Prices,
Global price of Brent Crude, USD/barrel, monthly), which is the standard
external reference used alongside domestic fuel/diesel CIPI sub-indices.

Usage:
    python src/ingest/build_global_oil_block.py \
        --raw data/raw/global_oil_brent_monthly.csv \
        --panel data/processed/panel_v1.0.csv \
        --out data/processed/panel_v1.0_brent.csv
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def load_brent(raw_path: Path) -> pd.Series:
    df = pd.read_csv(raw_path, parse_dates=["observation_date"])
    df = df.rename(columns={"observation_date": "date", "POILBREUSDM": "brent_crude_usd"})
    df = df.set_index("date").sort_index()
    s = pd.to_numeric(df["brent_crude_usd"], errors="coerce")
    # Match load_macro()'s month-start alignment / short-gap fill convention.
    s = s.resample("MS").mean().ffill(limit=2)
    s.name = "brent_crude_usd"
    return s


def attach(panel_path: Path, brent: pd.Series) -> pd.DataFrame:
    panel = pd.read_csv(panel_path, parse_dates=["date"]).set_index("date").sort_index()
    merged = panel.join(brent, how="left")
    return merged.reset_index()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Attach Brent crude oil as an auxiliary panel node.")
    p.add_argument("--raw", default="data/raw/global_oil_brent_monthly.csv")
    p.add_argument("--panel", default="data/processed/panel_v1.0.csv")
    p.add_argument("--out", default="data/processed/panel_v1.0_brent.csv")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    brent = load_brent(Path(args.raw))
    merged = attach(Path(args.panel), brent)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(out_path, index=False)

    coverage = merged["brent_crude_usd"].notna().mean() * 100
    print(f"Wrote {out_path} ({merged.shape[0]} rows x {merged.shape[1]} cols)")
    print(f"brent_crude_usd coverage over panel window: {coverage:.1f}%")


if __name__ == "__main__":
    main()
