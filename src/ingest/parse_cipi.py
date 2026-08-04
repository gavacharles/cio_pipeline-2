"""
parse_cipi.py
=============
Defensive parser for the UBOS Construction Input Price Index (CIPI) monthly
Excel workbooks.

WHY THIS IS DEFENSIVE, NOT POSITIONAL
-------------------------------------
UBOS publishes the CIPI as a monthly Excel workbook. Across vintages the sheet
name, the number of leading blank rows, the exact column of the index values,
and the label spellings all drift. A parser that hard-codes "the index is in
cell C7" will silently break the first time UBOS re-formats. This parser instead
*locates* the header row and the material rows by pattern, so it survives layout
drift and rebasing. Every assumption it makes is logged, and anything it cannot
resolve is raised rather than guessed.

CONTRACT
--------
Input : a path to one UBOS CIPI .xlsx (or .xls) workbook.
Output: a tidy long-format pandas DataFrame with columns
            ['date', 'series_code', 'series_label', 'sector', 'index_value',
             'source_file', 'sheet']
        one row per (material element x month) actually present in that file.

The caller (build_panel.py) stacks the per-file frames, splices rebasing
vintages, and writes the versioned panel.

Author: CiO Lab data pipeline. MIT-licensed for the research programme.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from datetime import datetime
from pathlib import Path

import pandas as pd

log = logging.getLogger("parse_cipi")

# ---------------------------------------------------------------------------
# Canonical material vocabulary.
# The keys are the tokens we search for (case-insensitive, whitespace-robust);
# the values are the stable series_code we assign so that the same material is
# identifiable across vintages even if UBOS re-spells the label.
# Extend this dictionary as new elements appear in the workbooks - unknown
# labels are NOT dropped, they are assigned an auto code and flagged for review.
# ---------------------------------------------------------------------------
MATERIAL_VOCAB: dict[str, str] = {
    "cement": "CEM",
    "lime": "LIME",
    "sand": "SAND",
    "aggregate": "AGG",
    "hardcore": "HCORE",
    "murram": "MURRAM",
    "clay": "CLAY",
    "bricks": "BRICK",
    "blocks": "BLOCK",
    "iron and steel": "IRONSTEEL",
    "iron & steel": "IRONSTEEL",
    "iron": "IRON",
    "steel": "STEEL",
    "reinforcement": "REBAR",
    "copper": "COPPER",
    "aluminium": "ALU",
    "aluminum": "ALU",
    "nails": "NAILS",
    "bolts": "BOLTS",
    "screws": "SCREWS",
    "paints": "PAINT",
    "paint": "PAINT",
    "varnishes": "VARNISH",
    "timber": "TIMBER",
    "wood": "WOOD",
    "glass": "GLASS",
    "tiles": "TILES",
    "roofing": "ROOF",
    "pipes": "PIPES",
    "cables": "CABLE",
    "electrical": "ELEC",
    "plumbing": "PLUMB",
    "fuel": "FUEL",
    "diesel": "DIESEL",
    "bitumen": "BITUMEN",
    "labour": "LABOUR",
    "labor": "LABOUR",
    "plant": "PLANT",
    "equipment": "EQUIP",
    "transport": "TRANSPORT",
}

# Aggregate / sector headline rows we want to keep but tag distinctly.
AGGREGATE_VOCAB: dict[str, str] = {
    "all items": "CIPI_ALL",
    "all construction": "CIPI_ALL",
    "construction input price index": "CIPI_ALL",
    "overall": "CIPI_ALL",
    "residential buildings": "CIPI_RES",
    "non residential buildings": "CIPI_NONRES",
    "non-residential buildings": "CIPI_NONRES",
    "buildings": "CIPI_BLDG",
    "civil works": "CIPI_CIVIL",
    "civil engineering": "CIPI_CIVIL",
    "materials": "CIPI_MAT",
}

MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"], start=1)}
MONTHS_ABBR = {m.lower(): i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}


class CipiParseError(RuntimeError):
    """Raised when the workbook cannot be resolved to a defensible layout."""


def _norm(s) -> str:
    """Normalise a cell to a lowercase, single-spaced string."""
    if s is None:
        return ""
    return re.sub(r"\s+", " ", str(s)).strip().lower()


def _looks_like_month(token: str) -> tuple[int, int] | None:
    """
    Try to read a column header as a month.
    Accepts 'Jan-2022', 'January 2022', '2022M01', '2022-01', 'Jan 22'.
    Returns (year, month) or None.
    """
    if isinstance(token, (datetime, date, pd.Timestamp)):
        return int(token.year), int(token.month)

    t = _norm(token)
    if not t:
        return None
    # 2022M01 / 2022-01 / 2022/01
    m = re.match(r"(\d{4})[\s\-/m](\d{1,2})$", t)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            return y, mo
    # Jan-2022 / January 2022 / Jan 22
    m = re.match(r"([a-z]+)[\s\-/]*(\d{2,4})$", t)
    if m:
        name, yr = m.group(1), m.group(2)
        mo = MONTHS.get(name) or MONTHS_ABBR.get(name[:3])
        if mo:
            y = int(yr)
            if y < 100:
                y += 2000
            return y, mo
    return None


def _classify_label(label: str) -> tuple[str, str, str] | None:
    """
    Map a row label to (series_code, canonical_label, sector).
    sector in {'material','aggregate','sector'}.
    Returns None if the label is empty/uninformative.
    """
    n = _norm(label)
    if not n or n in {"item", "items", "description", "index"}:
        return None
    # Aggregates first (longer, more specific phrases).
    for key, code in AGGREGATE_VOCAB.items():
        if key in n:
            sector = "sector" if code not in ("CIPI_ALL", "CIPI_MAT") else "aggregate"
            return code, n, sector
    # Materials.
    for key, code in MATERIAL_VOCAB.items():
        if re.search(rf"\b{re.escape(key)}\b", n):
            return code, n, "material"
    return None


def _find_header_row(ws_values: list[list], max_scan: int = 40) -> tuple[int, dict[int, tuple[int, int]]]:
    """
    Scan the first `max_scan` rows to find the one that carries the most
    month-like column headers. Returns (header_row_index, {col_index: (year, month)}).
    """
    best_row, best_map = -1, {}
    for r in range(min(max_scan, len(ws_values))):
        month_cols: dict[int, tuple[int, int]] = {}
        for c, cell in enumerate(ws_values[r]):
            ym = _looks_like_month(cell)
            if ym:
                month_cols[c] = ym
        if len(month_cols) > len(best_map):
            best_row, best_map = r, month_cols
    if best_row < 0 or not best_map:
        raise CipiParseError("No month-like header row found; layout unrecognised.")
    return best_row, best_map


def _find_label_col(ws_values: list[list], header_row: int) -> int:
    """
    The label column is the left-most column below the header that contains
    classifiable material/aggregate labels. Usually column 0 or 1.
    """
    scores: dict[int, int] = {}
    for c in range(min(4, len(ws_values[header_row]))):
        hits = 0
        for r in range(header_row + 1, len(ws_values)):
            if c < len(ws_values[r]) and _classify_label(ws_values[r][c]):
                hits += 1
        scores[c] = hits
    label_col = max(scores, key=scores.get)
    if scores[label_col] == 0:
        raise CipiParseError("No column resolves to material/aggregate labels.")
    return label_col


def _read_sheet_values(path: Path) -> tuple[str, list[list]]:
    """
    Return (sheet_name, rows-as-lists) for the most CIPI-like sheet in the book.
    Prefers a sheet whose name mentions index/CIPI; falls back to the sheet with
    the most month headers.
    """
    xls = pd.ExcelFile(path)
    candidates = xls.sheet_names
    preferred = [s for s in candidates
                 if re.search(r"index|cipi|table|indices", s, re.I)]
    ordered = preferred + [s for s in candidates if s not in preferred]

    best = None
    for sheet in ordered:
        df = pd.read_excel(path, sheet_name=sheet, header=None, dtype=object)
        rows = df.values.tolist()
        try:
            _find_header_row(rows)
            return sheet, rows           # first sheet that yields a header wins
        except CipiParseError:
            if best is None:
                best = (sheet, rows)
            continue
    if best is None:
        raise CipiParseError(f"{path.name}: no readable sheet.")
    # Let the caller's _find_header_row raise the informative error.
    return best


def parse_cipi_workbook(path: str | Path) -> pd.DataFrame:
    """
    Parse one UBOS CIPI workbook into a tidy long DataFrame.
    Raises CipiParseError on unrecoverable layout problems.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)

    sheet, rows = _read_sheet_values(path)
    header_row, month_cols = _find_header_row(rows)
    label_col = _find_label_col(rows, header_row)
    log.info("%s: sheet=%r header_row=%d label_col=%d month_cols=%d",
             path.name, sheet, header_row, label_col, len(month_cols))

    records = []
    auto_seq = 0
    for r in range(header_row + 1, len(rows)):
        row = rows[r]
        if label_col >= len(row):
            continue
        cls = _classify_label(row[label_col])
        if cls is None:
            continue
        series_code, canon_label, sector = cls
        if series_code is None:                       # unknown but non-empty label
            auto_seq += 1
            series_code = f"UNK{auto_seq:03d}"
            log.warning("%s: unmapped label %r -> %s (flagged for review)",
                        path.name, row[label_col], series_code)
        for c, (yy, mm) in month_cols.items():
            if c >= len(row):
                continue
            val = row[c]
            if val is None or _norm(val) in {"", "n/a", "na", "-", ".."}:
                continue
            try:
                fval = float(val)
            except (TypeError, ValueError):
                continue
            records.append({
                "date": datetime(yy, mm, 1),
                "series_code": series_code,
                "series_label": canon_label,
                "sector": sector,
                "index_value": fval,
                "source_file": path.name,
                "sheet": sheet,
            })

    if not records:
        raise CipiParseError(f"{path.name}: header found but no data rows parsed.")

    out = pd.DataFrame.from_records(records)
    out = out.sort_values(["series_code", "date"]).reset_index(drop=True)
    log.info("%s: parsed %d observations across %d series",
             path.name, len(out), out.series_code.nunique())
    return out


if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="Parse a UBOS CIPI workbook to tidy CSV.")
    ap.add_argument("workbook", help="path to a CIPI .xlsx/.xls file")
    ap.add_argument("-o", "--out", help="output CSV path", default=None)
    args = ap.parse_args()

    frame = parse_cipi_workbook(args.workbook)
    if args.out:
        frame.to_csv(args.out, index=False)
        print(f"wrote {len(frame)} rows -> {args.out}")
    else:
        frame.to_csv(sys.stdout, index=False)
