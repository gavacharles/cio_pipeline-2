#!/usr/bin/env python3
"""
Build macro_block.csv from manually exported MoFPED portal CSV files.

Drop one CSV per target series into data/raw/macro_manual/.
The script maps each file to a target `var` by filename keywords and extracts
(date, value) defensively.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd

VAR_KEYWORDS = {
    "exchange_rate": ["exchange", "usd", "fx", "bou_e"],
    "central_bank_rate": ["cbr", "central bank", "policy rate", "bou_mmi"],
    "lending_rate": ["lending", "interest", "bou_i"],
    "cpi": ["cpi", "inflation index"],
    "private_credit": ["private credit", "psc", "credit", "bou_psc"],
    "activity_indicator": ["activity", "iop", "kei", "output", "gdp"],
}

DATE_CANDIDATES = ["date", "period", "month", "time", "year_month"]
VALUE_CANDIDATES = ["value", "obs", "observation", "series", "data", "val"]

# Mapping for ugatsdb bulk-dump dataset files (e.g., BOU_E.csv, BOU_MMI.csv).
# Each var can map to one or more dataset prefixes and preferred series columns.
BULK_DATASET_MAP = {
    "exchange_rate": [("BOU_E", [r"^E_PA$", r"^E_EP$", r"^E_IFEM_MR$"])],
    "central_bank_rate": [("BOU_MMI", [r"^I_CBR$"])],
    "lending_rate": [
        ("BOU_MMI", [r"^I_LR$"]),
        ("BOU_I_M", [r"LENDING", r"^I_LR$"]),
        ("BOU_I", [r"^I_OVA$", r"^I_ONI$"]),
    ],
    "cpi": [
        ("BOU_CPI", [r"^CPI_16$", r"^CPI_09$", r"^CPI_HL_16$", r"^CPI_HL_09$"]),
        ("BOU_MMI", [r"^CPI_HL_16$", r"^CPI_HL_09$", r"^CPI_HL_05$"]),
    ],
    "private_credit": [("BOU_PSC", [r"^PSC$", r"PSC_TOTAL"])],
}


def infer_var(file_name: str) -> str | None:
    s = file_name.lower()
    for var, keys in VAR_KEYWORDS.items():
        if any(k in s for k in keys):
            return var
    return None


def choose_col(columns: list[str], candidates: list[str]) -> str | None:
    lc = [c.lower().strip() for c in columns]
    for cand in candidates:
        for i, c in enumerate(lc):
            if cand == c or cand in c:
                return columns[i]
    return None


def extract_series(path: Path, var: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    if df.empty:
        return pd.DataFrame(columns=["date", "var", "value", "source_file"])

    date_col = choose_col(list(df.columns), DATE_CANDIDATES)
    value_col = choose_col(list(df.columns), VALUE_CANDIDATES)

    if date_col is None:
        # fallback: first column parseable as date
        for c in df.columns:
            x = pd.to_datetime(df[c], errors="coerce")
            if x.notna().sum() >= max(3, int(0.3 * len(x))):
                date_col = c
                break

    if value_col is None:
        # fallback: first numeric-like column not date
        for c in df.columns:
            if c == date_col:
                continue
            x = pd.to_numeric(df[c], errors="coerce")
            if x.notna().sum() >= max(3, int(0.3 * len(x))):
                value_col = c
                break

    if date_col is None or value_col is None:
        raise RuntimeError(f"Could not infer date/value columns for {path.name}")

    out = pd.DataFrame(
        {
            "date": pd.to_datetime(df[date_col], errors="coerce").dt.to_period("M").dt.to_timestamp(),
            "var": var,
            "value": pd.to_numeric(df[value_col], errors="coerce"),
            "source_file": path.name,
        }
    ).dropna(subset=["date", "value"])

    return out


def _pick_column(columns: list[str], patterns: list[str]) -> str | None:
    for pat in patterns:
        rx = re.compile(pat, flags=re.IGNORECASE)
        for c in columns:
            if rx.search(c):
                return c
    return None


def extract_series_from_bulk(path: Path, var: str, patterns: list[str]) -> pd.DataFrame:
    df = pd.read_csv(path)
    if df.empty:
        return pd.DataFrame(columns=["date", "var", "value", "source_file"])

    date_col = choose_col(list(df.columns), DATE_CANDIDATES)
    if date_col is None:
        for c in df.columns:
            x = pd.to_datetime(df[c], errors="coerce")
            if x.notna().sum() >= max(3, int(0.3 * len(x))):
                date_col = c
                break
    if date_col is None:
        raise RuntimeError(f"Could not infer date column for {path.name}")

    value_col = _pick_column(list(df.columns), patterns)
    if value_col is None:
        raise RuntimeError(f"Could not match any target series columns in {path.name}")

    out = pd.DataFrame(
        {
            "date": pd.to_datetime(df[date_col], errors="coerce").dt.to_period("M").dt.to_timestamp(),
            "var": var,
            "value": pd.to_numeric(df[value_col], errors="coerce"),
            "source_file": path.name,
        }
    ).dropna(subset=["date", "value"])
    return out


def build(manual_dir: Path, out_csv: Path) -> pd.DataFrame:
    files = sorted(manual_dir.glob("*.csv"))
    if not files:
        raise RuntimeError(f"No CSV files found in {manual_dir}")

    frames = []
    skipped = []

    # First pass: explicit extraction from ugatsdb bulk dataset files.
    files_by_stem = {f.stem.upper(): f for f in files}
    for var, specs in BULK_DATASET_MAP.items():
        extracted = False
        for stem, col_patterns in specs:
            f = files_by_stem.get(stem.upper())
            if f is None:
                continue
            try:
                frames.append(extract_series_from_bulk(f, var, col_patterns))
                extracted = True
                break
            except Exception as e:  # noqa: BLE001
                skipped.append(f"{f.name} [{var}]: {e}")
        if not extracted:
            skipped.append(f"No bulk dataset match for var={var}")

    used_files = {f for f in files_by_stem.values() if any(f.stem.upper() == s for specs in BULK_DATASET_MAP.values() for s, _ in specs)}

    # Second pass: generic/manual extraction by filename keyword for remaining files.
    for f in files:
        if f in used_files:
            continue
        var = infer_var(f.name)
        if var is None:
            skipped.append(f.name)
            continue
        try:
            frames.append(extract_series(f, var))
        except Exception as e:  # noqa: BLE001
            skipped.append(f"{f.name}: {e}")

    if not frames:
        raise RuntimeError("No usable MoFPED CSV files parsed. Check file naming and columns.")

    out = pd.concat(frames, ignore_index=True)
    out = out.sort_values(["var", "date", "source_file"]).drop_duplicates(["var", "date"], keep="last")

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_csv, index=False)

    if skipped:
        (out_csv.parent / "macro_manual_skipped.txt").write_text("\n".join(skipped), encoding="utf-8")

    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Build macro_block.csv from manual MoFPED portal CSV exports.")
    ap.add_argument("--manual-dir", default="data/raw/macro_manual")
    ap.add_argument("--out", default="data/raw/macro_block.csv")
    args = ap.parse_args()

    out = build(Path(args.manual_dir), Path(args.out))
    print(out.groupby("var")["date"].agg(["min", "max", "count"]))
