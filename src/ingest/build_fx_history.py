#!/usr/bin/env python3
"""
build_fx_history.py — monthly local-currency-per-USD history for Kenya, Rwanda and Uganda.

The weekly snapshots (build_weekly_drivers.py) start in March 2024; the Kenya model needs
history back to 2019. Source: IMF Exchange Rates dataset (SDMX 2.1, no key), series
<ISO3>.XDC_USD.PA_RT.M = period-average national currency per USD.

Output: data/raw/fx_imf_monthly.csv  (date, kes_per_usd, rwf_per_usd, ugx_per_usd)

    python src/ingest/build_fx_history.py [--start 2015]
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "raw" / "fx_imf_monthly.csv"
URL = "https://api.imf.org/external/sdmx/2.1/data/IMF.STA,ER/{iso}.XDC_USD.PA_RT.M?startPeriod={start}"
SERIES = {"KEN": "kes_per_usd", "RWA": "rwf_per_usd", "UGA": "ugx_per_usd"}


def fetch(iso: str, start: int) -> pd.Series:
    with urlopen(Request(URL.format(iso=iso, start=start), headers={"User-Agent": "CiO Lab"}), timeout=90) as r:  # nosec B310
        xml = r.read().decode("utf-8")
    obs = dict(re.findall(r'TIME_PERIOD="(\d{4}-M\d{2})" OBS_VALUE="([0-9.]+)"', xml))
    obs.update({p: v for v, p in re.findall(r'OBS_VALUE="([0-9.]+)"[^>]*TIME_PERIOD="(\d{4}-M\d{2})"', xml)})
    s = pd.Series({pd.Timestamp(p.replace("-M", "-") + "-01"): float(v) for p, v in obs.items()})
    return s.sort_index().rename(SERIES[iso])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", type=int, default=2015)
    a = ap.parse_args()
    df = pd.concat([fetch(iso, a.start) for iso in SERIES], axis=1).rename_axis("date")
    df.round(4).to_csv(OUT)
    print(f"wrote {len(df)} months ({df.index.min():%Y-%m}..{df.index.max():%Y-%m}) -> {OUT}")


if __name__ == "__main__":
    main()
