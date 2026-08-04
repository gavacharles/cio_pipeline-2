#!/usr/bin/env python3
"""
reconcile_cipi.py
=================
Reconcile CIPI headline against CPI and PPI-manufacturing where overlap exists.

Outputs:
- data/processed/reconciliation_report.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def _norm_pair(df: pd.DataFrame, a: str, b: str) -> pd.DataFrame:
    pair = df[[a, b]].dropna().copy()
    if pair.empty:
        return pair
    pair[a] = 100 * pair[a] / pair[a].iloc[0]
    pair[b] = 100 * pair[b] / pair[b].iloc[0]
    return pair


def reconcile(panel_path: Path, out_path: Path) -> pd.DataFrame:
    panel = pd.read_parquet(panel_path) if panel_path.suffix == ".parquet" else pd.read_csv(panel_path)
    if not isinstance(panel.index, pd.DatetimeIndex):
        if "date" in panel.columns:
            panel["date"] = pd.to_datetime(panel["date"])
            panel = panel.set_index("date")

    rows = []
    cipi_col = "CIPI_ALL"
    comparators = [
        ("cpi", "CIPI vs CPI"),
        ("ppi_manufacturing", "CIPI vs PPI-manufacturing"),
    ]

    for comp, label in comparators:
        if cipi_col not in panel.columns:
            rows.append({"comparison": label, "status": "missing CIPI_ALL"})
            continue
        if comp not in panel.columns:
            rows.append({"comparison": label, "status": f"missing {comp}"})
            continue

        pair = _norm_pair(panel, cipi_col, comp)
        if len(pair) < 6:
            rows.append({"comparison": label, "status": "insufficient overlap", "n_overlap": len(pair)})
            continue

        gap = pair[cipi_col] - pair[comp]
        corr = float(pair[cipi_col].corr(pair[comp]))
        mad = float(np.abs(gap).mean())
        rmse = float(np.sqrt((gap ** 2).mean()))

        rows.append(
            {
                "comparison": label,
                "status": "ok",
                "n_overlap": int(len(pair)),
                "start": str(pair.index.min().date()),
                "end": str(pair.index.max().date()),
                "corr": round(corr, 4),
                "mad_index_points": round(mad, 3),
                "rmse_index_points": round(rmse, 3),
            }
        )

    out = pd.DataFrame(rows)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Reconcile CIPI with CPI/PPI where overlap exists.")
    ap.add_argument("--panel", default="data/processed/panel_v1.0.parquet")
    ap.add_argument("--out", default="data/processed/reconciliation_report.csv")
    args = ap.parse_args()
    df = reconcile(Path(args.panel), Path(args.out))
    print(df.to_string(index=False))
