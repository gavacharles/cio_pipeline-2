#!/usr/bin/env python3
"""
statssa_p01511.py — South Africa: Stats SA P0151.1 construction materials price indices.

Monthly release (PDF). Used here:
  Table 3  Construction input price index (CIPI), material purchases for the whole industry
           (weighted; Total construction, cement, ready-mix concrete, reinforcing steel, ...)
  Table 6  Civil engineering material price indices (totals)
Each release prints three months: the same month a year earlier, the previous month and the
reference month. Stats SA rebases (Dec 2021=100, Dec 2023=100) and reweights annually, so
history is built by chaining each release's own month-on-month change (settlement
history: chain_first_prints), and contracts settle on that same within-release change.

stats sa refuses non-browser clients (HTTP 403), so requests send browser-like headers.
PDFs are cached in data/raw/statssa/ (git-ignored; re-downloadable).

    python src/ingest/statssa_p01511.py pull [--start 2021-01]
    python src/ingest/statssa_p01511.py parse -o data/processed/statssa_p01511_long.csv
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "statssa"
URL = "https://www.statssa.gov.za/publications/P01511/P01511{month}{year}.pdf"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/126.0 Safari/537.36", "Referer": "https://www.statssa.gov.za/",
           "Accept": "application/pdf,*/*;q=0.8"}
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]
NUM = r"-?\d+(?:[  ]\d{3})*,\d+|-?\d+"
ROW = re.compile(rf"^(?P<label>.*?\S)\s{{2,}}(?P<nums>(?:(?:{NUM})\s+){{4,5}}(?:{NUM}))\s*$")
HEAD = re.compile(r"([A-Z][a-z]{2}) (\d{4})")


def pull(start: str = "2021-01") -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    new = 0
    for p in pd.period_range(start, pd.Timestamp(date.today()).to_period("M"), freq="M"):
        name = f"P01511{MONTHS[p.month - 1]}{p.year}.pdf"
        if (RAW / name).exists():
            continue
        try:
            with urlopen(Request(URL.format(month=MONTHS[p.month - 1], year=p.year), headers=HEADERS), timeout=90) as r:  # nosec B310
                data = r.read()
            if data[:4] == b"%PDF":
                (RAW / name).write_bytes(data)
                new += 1
        except Exception:
            pass                     # not yet published, or a different file name that month
    return new


def _num(s: str) -> float:
    return float(s.replace(" ", "").replace(" ", "").replace(",", "."))


def _table(lines: list[str], title: str) -> list[str]:
    """Body lines of the data table whose heading starts with `title` (the second
    occurrence; the first is the contents page)."""
    hits = [i for i, l in enumerate(lines) if l.strip().startswith(title)]
    if not hits:
        return []
    i = hits[-1] + 1
    out = []
    while i < len(lines) and not re.match(r"^\s*Table \d", lines[i]) and "Statistics South Africa" not in lines[i]:
        out.append(lines[i])
        i += 1
    return out


def parse_release(path: Path) -> pd.DataFrame:
    from parse_knbs_cipi import pdf_text      # same layout-preserving extraction
    lines = pdf_text(path).splitlines()
    rows = []
    for key, title, has_weight in [("cipi", "Table 3", True), ("civil", "Table 6", False)]:
        body = _table(lines, title)
        dates = None
        for l in body:
            heads = HEAD.findall(l)
            if len(heads) >= 3 and dates is None:
                dates = [pd.Timestamp(f"{m} {y}") for m, y in heads[:3]]
                continue
            m = ROW.match(l)
            if not m or dates is None:
                continue
            nums = re.findall(NUM, m.group("nums"))
            label = re.split(r"\s{3,}", m.group("label").strip())[-1]       # sub-items sit in a second column
            label = " ".join(label.split()).lower()
            vals = nums[1:4] if has_weight and len(nums) == 6 else nums[0:3]
            weight = _num(nums[0]) if has_weight and len(nums) == 6 else None
            for d, v in zip(dates, vals):
                rows.append({"table": key, "series_label": f"{key}|{label}", "weight": weight,
                             "date": d, "index_value": _num(v)})
    if not rows:
        raise ValueError(f"{path.name}: no tables parsed")
    df = pd.DataFrame(rows).drop_duplicates(["series_label", "date"])
    df["source_file"] = path.name
    df["release_month"] = df["date"].max()
    return df


def parse_all(paths) -> tuple[pd.DataFrame, list[str]]:
    sys.path.insert(0, str(ROOT / "src" / "ingest"))
    frames, failed = [], []
    for p in sorted(paths):
        try:
            frames.append(parse_release(Path(p)))
        except Exception:
            failed.append(Path(p).name)
    return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()), failed


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pull"); p.add_argument("--start", default="2021-01")
    p = sub.add_parser("parse"); p.add_argument("-o", "--out")
    a = ap.parse_args()
    if a.cmd == "pull":
        print(f"{pull(a.start)} new release(s); {len(list(RAW.glob('*.pdf')))} PDFs in {RAW}")
    else:
        df, failed = parse_all(RAW.glob("*.pdf"))
        print(f"parsed {df.source_file.nunique() if len(df) else 0} releases; failed: {failed}")
        if a.out:
            df.to_csv(a.out, index=False)


if __name__ == "__main__":
    main()
