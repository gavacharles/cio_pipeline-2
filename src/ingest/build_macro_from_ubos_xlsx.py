#!/usr/bin/env python3
"""
Build a partial macro block (CPI + PPI-manufacturing) from UBOS datasets Excel files.

This is a fallback when MoFPED `ugatsdb` connectivity is blocked.
Outputs long format compatible with build_panel.py: date,var,value,source_file.
"""

from __future__ import annotations

import argparse
import re
from datetime import date, datetime
from pathlib import Path

import pandas as pd


def _looks_like_month(token) -> tuple[int, int] | None:
    if isinstance(token, (datetime, date, pd.Timestamp)):
        return int(token.year), int(token.month)
    if token is None:
        return None
    s = str(token).strip()
    m = re.match(r"^(\d{4})[-/](\d{1,2})", s)
    if m:
        y, mm = int(m.group(1)), int(m.group(2))
        if 1 <= mm <= 12:
            return y, mm
    return None


def _find_header_row(df: pd.DataFrame, max_scan: int = 25) -> tuple[int, dict[int, tuple[int, int]]]:
    best_row = -1
    best_cols: dict[int, tuple[int, int]] = {}
    arr = df.values
    for r in range(min(max_scan, arr.shape[0])):
        cols = {}
        for c in range(arr.shape[1]):
            ym = _looks_like_month(arr[r, c])
            if ym:
                cols[c] = ym
        if len(cols) > len(best_cols):
            best_row, best_cols = r, cols
    if best_row < 0 or not best_cols:
        raise RuntimeError("No month header row found.")
    return best_row, best_cols


def _to_float(x):
    try:
        if x is None or (isinstance(x, str) and not x.strip()):
            return None
        return float(x)
    except Exception:
        return None


def _pick_row(df: pd.DataFrame, month_cols: dict[int, tuple[int, int]], patterns: list[str]) -> int:
    arr = df.values
    cand = []
    for r in range(arr.shape[0]):
        texts = [str(v).strip().lower() for v in arr[r] if isinstance(v, str)]
        if not texts:
            continue
        label_text = " | ".join(texts)
        if any(re.search(p, label_text, re.I) for p in patterns):
            nnum = 0
            for c in month_cols:
                v = _to_float(arr[r, c] if c < arr.shape[1] else None)
                if v is not None:
                    nnum += 1
            cand.append((nnum, r, label_text))
    if not cand:
        raise RuntimeError("Target row not found.")
    cand.sort(reverse=True)
    return cand[0][1]


def _extract_series(file_path: Path, var: str, row_patterns: list[str]) -> pd.DataFrame:
    xls = pd.ExcelFile(file_path)
    df = pd.read_excel(file_path, sheet_name=xls.sheet_names[0], header=None, dtype=object)
    _, month_cols = _find_header_row(df)
    row_idx = _pick_row(df, month_cols, row_patterns)

    recs = []
    for c, (yy, mm) in month_cols.items():
        v = _to_float(df.iat[row_idx, c] if c < df.shape[1] else None)
        if v is None:
            continue
        recs.append(
            {
                "date": datetime(yy, mm, 1),
                "var": var,
                "value": v,
                "source_file": file_path.name,
            }
        )
    if not recs:
        raise RuntimeError(f"No values extracted for {var} from {file_path.name}")
    return pd.DataFrame(recs)


def build(ubos_dir: Path, out_csv: Path):
    cpi_files = sorted(ubos_dir.glob("*CPI*.xls*"))
    ppi_files = sorted(ubos_dir.glob("*PPI*.xls*"))

    frames = []
    for f in cpi_files:
        try:
            frames.append(_extract_series(f, "cpi", [r"\bheadline\b", r"\ball items\b"]))
        except Exception:
            continue
    for f in ppi_files:
        try:
            frames.append(_extract_series(f, "ppi_manufacturing", [r"manufacturing\s*&\s*utilities", r"\bmanufacturing\b"]))
        except Exception:
            continue

    if not frames:
        raise RuntimeError("No CPI/PPI series extracted from UBOS Excel files.")

    long = pd.concat(frames, ignore_index=True)
    long = long.sort_values(["var", "date", "source_file"]).drop_duplicates(["var", "date"], keep="last")
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    long.to_csv(out_csv, index=False)
    return long


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Build partial macro_block.csv from UBOS CPI/PPI Excel files.")
    ap.add_argument("--ubos-dir", default="data/raw/ubos_cipi_downloads")
    ap.add_argument("--out", default="data/raw/macro_block.csv")
    args = ap.parse_args()

    out = build(Path(args.ubos_dir), Path(args.out))
    print(out.groupby("var")["date"].agg(["min", "max", "count"]))
