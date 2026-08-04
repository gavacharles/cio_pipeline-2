#!/usr/bin/env python3
"""
Fill sparse CIPI index columns using donor-series regression while preserving
observed values.

Targets:
- ALU
- CIPI_BLDG
- CIPI_CIVIL
- IRONSTEEL
- MURRAM
- NAILS

This creates a separate filled panel artifact and does not overwrite panel_v1.0.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

TARGETS = ["ALU", "CIPI_BLDG", "CIPI_CIVIL", "IRONSTEEL", "MURRAM", "NAILS"]


def _load_panel(path: Path) -> pd.DataFrame:
    if path.suffix == ".parquet":
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path, index_col=0)
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, errors="coerce")
    return df.sort_index()


def _donor_columns(df: pd.DataFrame) -> list[str]:
    exclude = set(TARGETS)
    out = []
    for c in df.columns:
        if c in exclude:
            continue
        s = pd.to_numeric(df[c], errors="coerce")
        # keep well-covered positive index-like donors
        if s.notna().sum() >= int(0.75 * len(df)) and (s.dropna() > 0).all():
            out.append(c)
    return out


def fill_targets(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    out = df.copy()
    donors = _donor_columns(df)
    report_rows = []

    X_all = np.log(df[donors].apply(pd.to_numeric, errors="coerce"))

    for t in TARGETS:
        if t not in df.columns:
            continue

        y = pd.to_numeric(df[t], errors="coerce")
        known = y.notna()
        n_known = int(known.sum())

        if n_known == 0:
            report_rows.append({
                "series": t,
                "method": "skipped_no_observations",
                "n_known": 0,
                "n_filled": 0,
                "train_r2": np.nan,
            })
            continue

        # Build training matrix where both y and donor X are available.
        Xk = X_all.loc[known].copy()
        train_mask = Xk.notna().all(axis=1)
        X_train = Xk.loc[train_mask]
        y_train = np.log(y.loc[X_train.index])

        filled_count = 0
        method = ""
        train_r2 = np.nan

        if len(X_train) >= 4:
            model = Ridge(alpha=1.0)
            model.fit(X_train.values, y_train.values)
            train_r2 = float(model.score(X_train.values, y_train.values))

            pred_mask = y.isna() & X_all.notna().all(axis=1)
            if pred_mask.any():
                yhat_log = model.predict(X_all.loc[pred_mask].values)
                yhat = np.exp(yhat_log)
                out.loc[pred_mask, t] = yhat
                filled_count = int(pred_mask.sum())
            method = "ridge_loglevel"

            # If any gaps remain (e.g., donor rows with NaNs), use ratio fallback.
            still_missing = out[t].isna()
            if still_missing.any():
                base_candidates = [
                    "CIPI_ALL", "CIPI_MAT", "AGG", "CLAY", "LABOUR", "IRON", "BRICK", "TIMBER"
                ]
                best_base = None
                best_n = 0
                for bname in base_candidates:
                    if bname not in df.columns:
                        continue
                    b = pd.to_numeric(df[bname], errors="coerce")
                    m = known & b.notna() & (b > 0)
                    n = int(m.sum())
                    if n > best_n:
                        best_n = n
                        best_base = bname
                if best_base is not None and best_n >= 2:
                    used_base = None
                    for bname in base_candidates:
                        if bname not in df.columns:
                            continue
                        b = pd.to_numeric(df[bname], errors="coerce")
                        m = known & b.notna() & (b > 0)
                        if int(m.sum()) < 2:
                            continue
                        ratio = float(np.median((y.loc[m] / b.loc[m]).values))
                        rmask = out[t].isna() & b.notna()
                        if rmask.any():
                            out.loc[rmask, t] = b.loc[rmask] * ratio
                            filled_count += int(rmask.sum())
                            used_base = bname if used_base is None else used_base
                    if used_base is not None:
                        method = f"ridge_plus_ratio_{used_base.lower()}"
        else:
            # Fallback: median ratio to best-overlap base series.
            base_candidates = [
                "CIPI_ALL", "CIPI_MAT", "AGG", "CLAY", "LABOUR", "IRON", "BRICK", "TIMBER"
            ]
            best_base = None
            best_n = 0
            for bname in base_candidates:
                if bname not in df.columns:
                    continue
                b = pd.to_numeric(df[bname], errors="coerce")
                m = known & b.notna() & (b > 0)
                n = int(m.sum())
                if n > best_n:
                    best_n = n
                    best_base = bname

            if best_base is not None and best_n >= 2:
                b = pd.to_numeric(df[best_base], errors="coerce")
                m = known & b.notna() & (b > 0)
                ratio = float(np.median((y.loc[m] / b.loc[m]).values))
                pred_mask = y.isna() & b.notna()
                out.loc[pred_mask, t] = b.loc[pred_mask] * ratio
                filled_count = int(pred_mask.sum())
                method = f"ratio_to_{best_base.lower()}"
            else:
                method = "insufficient_overlap"

        report_rows.append({
            "series": t,
            "method": method,
            "n_known": n_known,
            "n_filled": filled_count,
            "train_r2": train_r2,
        })

    report = pd.DataFrame(report_rows)
    return out, report


def main() -> None:
    ap = argparse.ArgumentParser(description="Fill sparse index columns in a separate panel artifact.")
    ap.add_argument("--in-panel", default="data/processed/panel_v1.0.parquet")
    ap.add_argument("--out-prefix", default="data/processed/panel_v1.0_filled")
    args = ap.parse_args()

    inp = Path(args.in_panel)
    prefix = Path(args.out_prefix)

    panel = _load_panel(inp)
    filled, report = fill_targets(panel)

    pq = prefix.parent / f"{prefix.name}.parquet"
    csv = prefix.parent / f"{prefix.name}.csv"
    xlsx = prefix.parent / f"{prefix.name}.xlsx"
    rep = prefix.parent / f"{prefix.name}_fill_report.csv"
    man = prefix.parent / f"{prefix.name}_fill_manifest.json"

    filled.to_parquet(pq)
    filled.to_csv(csv)
    filled.to_excel(xlsx, sheet_name="panel_filled")
    report.to_csv(rep, index=False)

    manifest = {
        "input_panel": str(inp),
        "output_panel": str(pq),
        "targets": TARGETS,
        "rows": int(filled.shape[0]),
        "columns": int(filled.shape[1]),
        "report": str(rep),
    }
    man.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(report.to_string(index=False))
    print(f"wrote: {pq}")
    print(f"wrote: {csv}")
    print(f"wrote: {xlsx}")


if __name__ == "__main__":
    main()
