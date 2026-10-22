#!/usr/bin/env python3
"""
parse_knbs_cipi.py — parse KNBS Construction Input Price Index release PDFs.

KNBS's layout changed over time (2021-22 releases: Building, Civil, then an
aggregates-only Overall table; 2023+: a full Overall table first, then Building
and Civil), and some releases are scanned images with no text layer. So tables
are found by their header row (a "Weight" column followed by period columns such
as Dec-19 or Q3-2024), and the table's sheet is read from the title above it.

Output, one row per (release, sheet, series, quarter):
    source_file, release_period, sheet (ALL | BUILDINGS | CIVIL), series_label,
    is_aggregate, weight, date (quarter start), index_value

    python src/ingest/parse_knbs_cipi.py data/raw/knbs/*.pdf -o data/processed/knbs_cipi_long.csv
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from pathlib import Path

import pandas as pd

PERIOD = re.compile(r"\b(Dec-19|Q[1-4]-\d{4})\b")
NUM = re.compile(r"^\(?-?\d+(?:\.\d+)?\)?$")
AGGREGATES = {"materials", "labour", "total labour", "equipment", "transport, fuels and lubricants",
              "transport, fuel and lubricants", "transport and fuel"}
TOTAL_WORDS = ("cost index", "construction cost indices", "price index")


class KnbsParseError(RuntimeError):
    pass


def pdf_text(path: Path) -> str:
    """Layout-preserving text: poppler's pdftotext if installed, else pypdf's layout mode."""
    if shutil.which("pdftotext"):
        try:   # a first read can stall while a cloud-synced folder fetches the file
            return subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True,
                                  stdin=subprocess.DEVNULL, timeout=180, check=False).stdout
        except subprocess.TimeoutExpired:
            pass
    from pypdf import PdfReader
    return "\n".join(p.extract_text(extraction_mode="layout") or "" for p in PdfReader(path).pages)


def _period_start(tok: str) -> pd.Timestamp:
    if tok == "Dec-19":
        return pd.Timestamp("2019-10-01")          # base period = Q4 2019
    q, y = int(tok[1]), int(tok[3:])
    return pd.Timestamp(year=y, month=3 * (q - 1) + 1, day=1)


def _sheet(title: str) -> str | None:
    t = title.lower()
    if "building" in t:
        return "BUILDINGS"
    if "civil" in t:
        return "CIVIL"
    if "aggregat" in t or "overall construction" in t or "construction input price indices" in t:
        return "ALL"
    return None


def _norm(s: str) -> str:
    return " ".join(s.replace("Indices", "Index").split()).lower()


def parse_release(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    lines = pdf_text(path).splitlines()
    records = []
    i = 0
    while i < len(lines):
        line = lines[i]
        periods = PERIOD.findall(line)
        if not (re.search(r"\bWeights?\b", line, re.I) and len(periods) >= 2):
            i += 1
            continue
        # the table's title is the nearest "Table N" heading above the header (else the lines just above)
        start = next((j for j in range(i, max(-1, i - 6), -1) if re.match(r"^\s*Table\s+\d", lines[j])), i - 2)
        sheet = _sheet(" ".join(lines[max(0, start):i + 1]))
        dates = [_period_start(p) for p in periods]
        n = len(dates)
        i += 1
        while i < len(lines):
            row = lines[i]
            if PERIOD.findall(row) and re.search(r"Weight", row, re.I):
                break                                   # next table header
            if re.match(r"^\s*Table\s+\d", row) or "|P age" in row:
                if records and records[-1]["sheet"] == sheet and re.match(r"^\s*Table\s+\d", row):
                    break
            toks = row.split()
            i += 1
            if len(toks) < n + 2 or not all(NUM.match(t) for t in toks[-(n + 1):]):
                continue
            label_toks = toks[:-(n + 1)]
            has_sno = bool(label_toks) and label_toks[0].isdigit()
            if has_sno:
                label_toks = label_toks[1:]
            if not label_toks:
                continue
            label = _norm(" ".join(label_toks))
            weight = float(toks[-(n + 1)].strip("()"))
            is_total = any(w in label for w in TOTAL_WORDS)
            is_agg = is_total or (label in AGGREGATES) or not has_sno
            for d, v in zip(dates, toks[-n:]):
                val = float(v.strip("()"))
                records.append({"sheet": sheet, "series_label": "total" if is_total else label,
                                "is_aggregate": is_agg, "weight": weight, "date": d, "index_value": val})
    if not records:
        raise KnbsParseError(f"{path.name}: no tables found (scanned PDF or new layout)")
    out = pd.DataFrame(records).dropna(subset=["sheet"])
    out["source_file"] = path.name
    out["release_period"] = out["date"].max()
    return out.drop_duplicates(["sheet", "series_label", "date"], keep="first")


def parse_all(paths) -> tuple[pd.DataFrame, list[str]]:
    frames, failed = [], []
    for p in sorted(paths):
        try:
            frames.append(parse_release(p))
        except KnbsParseError:
            failed.append(Path(p).name)
    return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()), failed


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdfs", nargs="+")
    ap.add_argument("-o", "--out")
    args = ap.parse_args()
    df, failed = parse_all(args.pdfs)
    print(f"parsed {df.source_file.nunique() if len(df) else 0} releases, {len(df)} rows; "
          f"no text tables in: {failed}")
    if args.out:
        df.to_csv(args.out, index=False)


if __name__ == "__main__":
    main()
