#!/usr/bin/env python3
"""
Build a standalone government fiscal panel from downloaded MOFPED bulk datasets.

Requested indicators:
- total central government revenue
- overall public expenditure
- fiscal deficits
- total public debt

Primary source dataset: MOF_POE
Fallbacks: MOF_TOT / MOF_TOT_14 where needed.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def _read(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def _series(df: pd.DataFrame, date_col: str, val_col: str) -> pd.Series:
    if df.empty or date_col not in df.columns or val_col not in df.columns:
        return pd.Series(dtype=float)
    dt = pd.to_datetime(df[date_col], errors="coerce")
    idx = dt.dt.to_period("M").dt.to_timestamp()
    out = pd.Series(pd.to_numeric(df[val_col], errors="coerce").values,
                    index=idx)
    out = out.dropna()
    out = out[~out.index.isna()]
    return out[~out.index.duplicated(keep="last")].sort_index()


def build(raw_dir: Path, out_csv: Path, out_xlsx: Path) -> pd.DataFrame:
    ds = raw_dir / "mofped_bulk" / "datasets"

    poe = _read(ds / "MOF_POE.csv")
    tot = _read(ds / "MOF_TOT.csv")
    tot14 = _read(ds / "MOF_TOT_14.csv")

    revenue = _series(poe, "Date", "REV")
    if revenue.empty:
        revenue = _series(tot, "Date", "REV")
    if revenue.empty:
        revenue = _series(tot14, "Date", "REV_GRA_14")

    expenditure = _series(poe, "Date", "EXP_LEN")
    if expenditure.empty:
        expenditure = _series(tot, "Date", "EXP_LEN")
    if expenditure.empty:
        expenditure = _series(tot14, "Date", "EXP_14")

    deficit = _series(poe, "Date", "BAL_FIS")
    if deficit.empty:
        deficit = _series(tot, "Date", "BAL_FIS")
    if deficit.empty:
        deficit = _series(tot14, "Date", "NA_FIN_14")

    # Best available debt-like series in downloaded MOFPED panel:
    # MOF_POE: DD_TI = Domestic Debt: Total Issuance (UGX Billion)
    debt = _series(poe, "Date", "DD_TI")

    idx = revenue.index.union(expenditure.index).union(deficit.index).union(debt.index)
    panel = pd.DataFrame(index=idx)
    panel.index.name = "date"

    panel["total_central_government_revenue"] = revenue.reindex(idx)
    panel["overall_public_expenditure"] = expenditure.reindex(idx)
    panel["fiscal_deficit"] = deficit.reindex(idx)
    panel["total_public_debt"] = debt.reindex(idx)

    panel = panel.sort_index()

    # keep only rows where at least one requested indicator exists
    panel = panel.dropna(how="all")

    # add metadata columns for transparency
    panel["revenue_source"] = "MOF_POE.REV (fallback MOF_TOT.REV / MOF_TOT_14.REV_GRA_14)"
    panel["expenditure_source"] = "MOF_POE.EXP_LEN (fallback MOF_TOT.EXP_LEN / MOF_TOT_14.EXP_14)"
    panel["deficit_source"] = "MOF_POE.BAL_FIS (fallback MOF_TOT.BAL_FIS / MOF_TOT_14.NA_FIN_14)"
    panel["debt_source"] = "MOF_POE.DD_TI (Domestic Debt: Total Issuance, UGX bn)"

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    panel.reset_index().to_csv(out_csv, index=False)
    panel.reset_index().to_excel(out_xlsx, index=False, sheet_name="government_fiscal_panel")

    return panel.reset_index()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Build standalone government fiscal panel from MOFPED downloaded data.")
    ap.add_argument("--raw", default="data/raw", help="Raw data root")
    ap.add_argument("--out-csv", default="data/processed/government_fiscal_panel.csv")
    ap.add_argument("--out-xlsx", default="data/processed/government_fiscal_panel.xlsx")
    args = ap.parse_args()

    df = build(Path(args.raw), Path(args.out_csv), Path(args.out_xlsx))
    print(df[["date", "total_central_government_revenue", "overall_public_expenditure", "fiscal_deficit", "total_public_debt"]].head().to_string(index=False))
    print("rows:", len(df), "range:", df["date"].min(), "->", df["date"].max())
