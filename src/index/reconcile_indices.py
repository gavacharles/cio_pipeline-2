#!/usr/bin/env python3
"""
reconcile_indices.py
====================
Reconcile CIPI headline against CPI and PPI-manufacturing where overlap exists.

Outputs:
- data/processed/reconciliation_summary.csv
- data/processed/reconciliation_notes.md
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def yoy_log(series: pd.Series) -> pd.Series:
    return np.log(series) - np.log(series.shift(12))


def overlap_metrics(a: pd.Series, b: pd.Series, a_name: str, b_name: str) -> dict:
    d = pd.concat([a.rename("a"), b.rename("b")], axis=1).dropna()
    if d.empty:
        return {
            "left": a_name,
            "right": b_name,
            "start": None,
            "end": None,
            "n": 0,
            "corr_level": np.nan,
            "corr_yoy": np.nan,
            "median_abs_yoy_spread": np.nan,
        }

    ay = yoy_log(d["a"])
    by = yoy_log(d["b"])
    yy = pd.concat([ay.rename("ay"), by.rename("by")], axis=1).dropna()

    return {
        "left": a_name,
        "right": b_name,
        "start": str(d.index.min().date()),
        "end": str(d.index.max().date()),
        "n": int(len(d)),
        "corr_level": float(d["a"].corr(d["b"])),
        "corr_yoy": float(yy["ay"].corr(yy["by"])) if not yy.empty else np.nan,
        "median_abs_yoy_spread": float((yy["ay"] - yy["by"]).abs().median()) if not yy.empty else np.nan,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Reconcile CIPI vs CPI/PPI-manufacturing.")
    ap.add_argument("--panel", default="data/processed/panel_v1.0.parquet")
    ap.add_argument("--out", default="data/processed")
    args = ap.parse_args()

    panel = pd.read_parquet(args.panel)
    panel.index = pd.to_datetime(panel.index)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    cipi_col = "CIPI_ALL" if "CIPI_ALL" in panel.columns else None
    cpi_col = "cpi" if "cpi" in panel.columns else None

    ppi_candidates = [
        c
        for c in panel.columns
        if c.lower() in {"ppi", "ppi_manufacturing", "ppi_manufacturing_utilities", "ppi_mu"}
        or ("ppi" in c.lower() and "manufact" in c.lower())
    ]

    rows = []
    notes = []

    if cipi_col is None:
        notes.append("CIPI headline series `CIPI_ALL` not found in panel.")
    if cpi_col is None:
        notes.append("CPI series `cpi` not found in panel.")

    if cipi_col and cpi_col:
        rows.append(overlap_metrics(panel[cipi_col], panel[cpi_col], cipi_col, cpi_col))

    if cipi_col and ppi_candidates:
        for ppi in ppi_candidates:
            rows.append(overlap_metrics(panel[cipi_col], panel[ppi], cipi_col, ppi))
    elif cipi_col and not ppi_candidates:
        notes.append("No PPI-manufacturing column found in panel.")

    summary = pd.DataFrame(rows)
    summary_path = out_dir / "reconciliation_summary.csv"
    summary.to_csv(summary_path, index=False)

    note_path = out_dir / "reconciliation_notes.md"
    if summary.empty:
        notes.append("No reconciliation pairs could be evaluated with current panel columns.")
    else:
        notes.append(f"Computed {len(summary)} reconciliation pair(s).")
    note_path.write_text("\n".join(f"- {n}" for n in notes) + "\n")

    print(f"Wrote {summary_path}")
    print(f"Wrote {note_path}")


if __name__ == "__main__":
    main()
