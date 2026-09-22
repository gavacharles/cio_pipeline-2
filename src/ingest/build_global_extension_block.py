#!/usr/bin/env python3
"""
build_global_extension_block.py
================================
Fold additional external auxiliary nodes into the CiO panel, alongside Brent
crude (see build_global_oil_block.py). Extends coverage of the transport-cost
and metals-input channels that neither MoFPED nor UBOS carry:

- iron_ore_usd: FRED PIORECRUSDM (IMF Primary Commodity Prices, Global price
  of Iron Ore, USD/metric ton, monthly). Parallels Brent for the IRON /
  IRONSTEEL / STEEL CIPI sub-indices, same source family/methodology as Brent.
- gscpi: NY Fed Global Supply Chain Pressure Index (standardized z-score,
  monthly, https://www.newyorkfed.org/research/policy/gscpi). Proxy for
  global shipping/freight-cost pressure -- Uganda is landlocked, so import
  transport cost is a real channel with no domestic series covering it. We
  use GSCPI rather than the Baltic Dry Index because it is free, documented,
  and already published as a clean monthly time series; a raw BDI series is
  not freely available for a reproducible pipeline.

Usage:
    python src/ingest/build_global_extension_block.py \
        --panel data/processed/panel_v1.0_brent.csv \
        --out data/processed/panel_v1.0_extended.csv
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def load_iron_ore(raw_path: Path) -> pd.Series:
    df = pd.read_csv(raw_path, parse_dates=["observation_date"])
    df = df.rename(columns={"observation_date": "date", "PIORECRUSDM": "iron_ore_usd"})
    df = df.set_index("date").sort_index()
    s = pd.to_numeric(df["iron_ore_usd"], errors="coerce")
    s = s.resample("MS").mean().ffill(limit=2)
    s.name = "iron_ore_usd"
    return s


def load_gscpi(raw_path: Path) -> pd.Series:
    df = pd.read_excel(raw_path, sheet_name="GSCPI Monthly Data")
    df = df.dropna(subset=["Date", "GSCPI"])
    df["date"] = pd.to_datetime(df["Date"])
    df = df.set_index("date").sort_index()
    s = pd.to_numeric(df["GSCPI"], errors="coerce")
    s = s.resample("MS").mean().ffill(limit=2)
    s.name = "gscpi_supply_chain_pressure"
    return s


def attach(panel_path: Path, series_list: list[pd.Series]) -> pd.DataFrame:
    panel = pd.read_csv(panel_path, parse_dates=["date"]).set_index("date").sort_index()
    merged = panel
    for s in series_list:
        merged = merged.join(s, how="left")
    return merged.reset_index()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Attach iron ore + GSCPI as auxiliary panel nodes.")
    p.add_argument("--iron-ore-raw", default="data/raw/global_iron_ore_monthly.csv")
    p.add_argument("--gscpi-raw", default="data/raw/global_gscpi_monthly.xlsx")
    p.add_argument("--panel", default="data/processed/panel_v1.0_brent.csv")
    p.add_argument("--out", default="data/processed/panel_v1.0_extended.csv")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    iron_ore = load_iron_ore(Path(args.iron_ore_raw))
    gscpi = load_gscpi(Path(args.gscpi_raw))
    merged = attach(Path(args.panel), [iron_ore, gscpi])

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(out_path, index=False)

    for col in ["iron_ore_usd", "gscpi_supply_chain_pressure"]:
        coverage = merged[col].notna().mean() * 100
        print(f"{col} coverage over panel window: {coverage:.1f}%")
    print(f"Wrote {out_path} ({merged.shape[0]} rows x {merged.shape[1]} cols)")


if __name__ == "__main__":
    main()
