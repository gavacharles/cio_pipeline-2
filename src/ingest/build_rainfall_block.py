#!/usr/bin/env python3
"""
build_rainfall_block.py — monthly rainfall for Uganda's main construction markets.

Wet months interrupt sand, murram and aggregate extraction and haulage and slow site
work, so rainfall is a candidate driver for the quarry components of the CIPI
(config/forecast_model.yaml). Source: ERA5 daily precipitation via the Open-Meteo
archive API (no key), five towns averaged with equal weight.

Output: data/raw/rainfall_era5_monthly.csv
    date, rain_mm (monthly total, 5-town mean), rain_anomaly (standardised by calendar
    month against the full record; > 0 = wetter than usual for that month)

    python src/ingest/build_rainfall_block.py [--start 2015-01-01] [--end YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from urllib.request import urlopen

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SITES = {  # town: (lat, lon)
    "Kampala": (0.3476, 32.5825), "Jinja": (0.4244, 33.2042), "Mbarara": (-0.6072, 30.6545),
    "Gulu": (2.7724, 32.2881), "Mbale": (1.0647, 34.1797),
}
API = "https://archive-api.open-meteo.com/v1/archive"


def fetch(start: str, end: str) -> pd.DataFrame:
    lat = ",".join(str(v[0]) for v in SITES.values())
    lon = ",".join(str(v[1]) for v in SITES.values())
    url = (f"{API}?latitude={lat}&longitude={lon}&start_date={start}&end_date={end}"
           "&daily=precipitation_sum&timezone=Africa%2FKampala")
    with urlopen(url, timeout=180) as r:  # nosec B310 - fixed public API
        data = json.load(r)
    frames = []
    for town, d in zip(SITES, data):
        frames.append(pd.Series(d["daily"]["precipitation_sum"], index=pd.to_datetime(d["daily"]["time"]),
                                name=town, dtype=float))
    return pd.concat(frames, axis=1)


def monthly(daily: pd.DataFrame) -> pd.DataFrame:
    days = daily.notna().all(axis=1).groupby(daily.index.to_period("M")).sum()
    full = days[days.values == days.index.days_in_month].index
    m = daily.groupby(daily.index.to_period("M")).sum(min_count=1).mean(axis=1)
    m = m[m.index.isin(full)]                      # complete months only
    out = pd.DataFrame({"rain_mm": m})
    g = out.groupby(out.index.month)["rain_mm"]
    out["rain_anomaly"] = (out["rain_mm"] - g.transform("mean")) / g.transform("std")
    out.index = out.index.to_timestamp()
    return out.rename_axis("date")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", default="2015-01-01")
    ap.add_argument("--end", default=date.today().isoformat())
    ap.add_argument("--out", default=str(ROOT / "data" / "raw" / "rainfall_era5_monthly.csv"))
    args = ap.parse_args()
    out = monthly(fetch(args.start, args.end)).round(3)
    out.to_csv(args.out)
    print(f"wrote {len(out)} months ({out.index.min():%Y-%m}..{out.index.max():%Y-%m}) -> {args.out}")


if __name__ == "__main__":
    main()
