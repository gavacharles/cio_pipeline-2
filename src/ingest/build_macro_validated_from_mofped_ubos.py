#!/usr/bin/env python3
"""
Build a validated macro block for the combined panel using explicit MOFPED series
and UBOS cross-checks (for CPI) plus UBOS PPI-manufacturing.

Outputs a strict long schema: date,var,value,source_file
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


MOFPED_MAP = {
    "activity_indicator": "CIEA",
    "central_bank_rate": "I_BOU_CBR",
    "cpi": "CPI_16",
    "exchange_rate": "E_USD",
    "lending_rate": "I_BA_UGX_L",
    "private_credit": "PSC",
}


def _extract_series(df: pd.DataFrame, date_col: str, value_col: str, var: str, source_file: str) -> pd.DataFrame:
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(df[date_col], errors="coerce").dt.to_period("M").dt.to_timestamp(),
            "var": var,
            "value": pd.to_numeric(df[value_col], errors="coerce"),
            "source_file": source_file,
        }
    )
    out = out.dropna(subset=["date", "value"]).sort_values("date")
    out = out.drop_duplicates(subset=["date"], keep="last")
    return out


def build(raw_dir: Path, out_csv: Path, crosscheck_out: Path | None = None) -> pd.DataFrame:
    ds = raw_dir / "mofped_bulk" / "datasets"
    poe_path = ds / "MOF_POE.csv"
    if not poe_path.exists():
        raise FileNotFoundError(f"Missing {poe_path}")

    poe = pd.read_csv(poe_path)

    frames: list[pd.DataFrame] = []
    for var, col in MOFPED_MAP.items():
        if col not in poe.columns:
            raise RuntimeError(f"MOF_POE missing required column: {col} for var={var}")
        frames.append(_extract_series(poe, "Date", col, var, "MOF_POE.csv"))

    macro = pd.concat(frames, ignore_index=True)

    # UBOS CPI/PPI cross-check/fill
    ubos_path = raw_dir / "macro_block_ubos.csv"
    cross_rows = []
    if ubos_path.exists():
        ub = pd.read_csv(ubos_path)
        if {"date", "var", "value"}.issubset(set(ub.columns)):
            ub["date"] = pd.to_datetime(ub["date"], errors="coerce").dt.to_period("M").dt.to_timestamp()
            ub["value"] = pd.to_numeric(ub["value"], errors="coerce")

            ub_cpi = ub[ub["var"] == "cpi"].dropna(subset=["date", "value"])[["date", "value"]].rename(columns={"value": "ubos_cpi"})
            mf_cpi = macro[macro["var"] == "cpi"][['date', 'value']].rename(columns={"value": "mofped_cpi"}).sort_values("date")
            merged = mf_cpi.merge(ub_cpi, on="date", how="inner").sort_values("date")
            if not merged.empty:
                # UBOS extraction here is monthly inflation-rate-like (roughly
                # around -1 to +2), not CPI index levels. Compare like-for-like
                # using MOFPED monthly inflation from CPI_16 levels.
                if merged["ubos_cpi"].abs().median() < 10:
                    merged["mofped_cpi_mom"] = merged["mofped_cpi"].pct_change() * 100.0
                    cmp = merged.dropna(subset=["mofped_cpi_mom", "ubos_cpi"]).copy()
                    if not cmp.empty:
                        cmp["abs_diff"] = (cmp["mofped_cpi_mom"] - cmp["ubos_cpi"]).abs()
                        cross_rows.append(
                            {
                                "comparison": "MOFPED CPI_16 MoM inflation vs UBOS CPI MoM",
                                "n_overlap": int(len(cmp)),
                                "mean_abs_diff": float(cmp["abs_diff"].mean()),
                                "max_abs_diff": float(cmp["abs_diff"].max()),
                            }
                        )
                else:
                    merged["abs_diff"] = (merged["mofped_cpi"] - merged["ubos_cpi"]).abs()
                    cross_rows.append(
                        {
                            "comparison": "MOFPED CPI_16 index vs UBOS CPI index",
                            "n_overlap": int(len(merged)),
                            "mean_abs_diff": float(merged["abs_diff"].mean()),
                            "max_abs_diff": float(merged["abs_diff"].max()),
                        }
                    )

            # Fill only missing MOFPED cpi dates with UBOS cpi
            ub_fill = ub[ub["var"] == "cpi"].dropna(subset=["date", "value"]).copy()
            ub_fill["source_file"] = "macro_block_ubos.csv"
            ub_fill = ub_fill[["date", "var", "value", "source_file"]]

            existing_cpi_dates = set(macro.loc[macro["var"] == "cpi", "date"])
            ub_fill = ub_fill[~ub_fill["date"].isin(existing_cpi_dates)]
            if not ub_fill.empty:
                macro = pd.concat([macro, ub_fill], ignore_index=True)

            # Ensure ppi_manufacturing included for reconciliation
            ppi = ub[ub["var"] == "ppi_manufacturing"].dropna(subset=["date", "value"]).copy()
            if not ppi.empty:
                ppi["source_file"] = "macro_block_ubos.csv"
                ppi = ppi[["date", "var", "value", "source_file"]]
                macro = pd.concat([macro, ppi], ignore_index=True)

    macro = macro.dropna(subset=["date", "var", "value"]) \
                 .sort_values(["var", "date", "source_file"]) \
                 .drop_duplicates(["var", "date"], keep="last")

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    macro.to_csv(out_csv, index=False)

    if crosscheck_out is not None:
        pd.DataFrame(cross_rows).to_csv(crosscheck_out, index=False)

    return macro


def main() -> None:
    ap = argparse.ArgumentParser(description="Build validated macro block from MOFPED + UBOS cross-check.")
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--out", default="data/raw/macro_block.csv")
    ap.add_argument("--crosscheck-out", default="data/processed/macro_crosscheck_report.csv")
    args = ap.parse_args()

    raw_dir = Path(args.raw)
    out = Path(args.out)
    cross = Path(args.crosscheck_out)
    df = build(raw_dir, out, cross)
    out_pq = out.with_suffix(".parquet")
    df.to_parquet(out_pq, index=False)

    print(df.groupby("var")["date"].agg(["min", "max", "count"]))
    print(f"wrote: {out}")
    print(f"wrote: {out_pq}")
    print(f"wrote: {cross}")


if __name__ == "__main__":
    main()
