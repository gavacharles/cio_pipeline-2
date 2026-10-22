#!/usr/bin/env python3
"""
build_weekly_drivers.py — weekly macro readings for the weekly forecast note.

Contractors price jobs weekly; UBOS publishes monthly, 1-2 months late, and KNBS
quarterly. This script keeps the fast-moving drivers current:
  - Brent crude, daily (EIA RBRTE spreadsheet; FRED DCOILBRENTEU as fallback)
  - UGX, KES, RWF per USD, one reading per week (fawazahmed0 currency-api, dated
    snapshots on jsDelivr; cached, so each run only fetches new weeks)

Outputs
  data/raw/weekly_drivers.csv               weekly (Friday) readings since 2024-03
  data/processed/macro_extension_monthly.csv monthly means after the macro panel ends,
      spliced to the panel's own series by their ratio in the last overlapping month,
      with `days` = observations behind each month (the current month is partial)

    python src/ingest/build_weekly_drivers.py
"""
from __future__ import annotations

import io
import json
from datetime import date, timedelta
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
WEEKLY = ROOT / "data" / "raw" / "weekly_drivers.csv"
EXT = ROOT / "data" / "processed" / "macro_extension_monthly.csv"
PANEL = ROOT / "data" / "processed" / "panel_v1.0_extended.csv"
FX_URL = "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{d}/v1/currencies/usd.json"
FX_START = date(2024, 3, 8)            # first dated snapshot available


def _currencies() -> dict[str, str]:
    """currency-api code -> column, for every country config with an fx_code."""
    import yaml
    out = {}
    for f in sorted((ROOT / "config" / "countries").glob("*.yaml")):
        fx = (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("fx_code")
        if fx:
            out[fx] = f"{fx}_per_usd"
    return out


CURRENCIES = _currencies()


def _get(url: str, timeout: int = 60) -> bytes:
    with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0 (CiO Lab)"}), timeout=timeout) as r:  # nosec B310
        return r.read()


def brent_daily() -> pd.Series:
    try:
        raw = pd.read_excel(io.BytesIO(_get("https://www.eia.gov/dnav/pet/hist_xls/RBRTEd.xls")),
                            sheet_name="Data 1", skiprows=2)
        s = raw.set_index(raw.columns[0])[raw.columns[1]]
    except Exception:
        raw = pd.read_csv(io.BytesIO(_get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILBRENTEU")))
        s = pd.to_numeric(raw.set_index(raw.columns[0])[raw.columns[1]], errors="coerce")
    s.index = pd.to_datetime(s.index)
    return s.dropna().astype(float).rename("brent_usd")


def fx_weekly(cached: pd.DataFrame | None, backfill: bool = False) -> pd.DataFrame:
    # every cached week counts as fetched, unless a currency was added since (then back-fill once)
    have = set() if (cached is None or backfill) else set(cached.index.date)
    rows = []
    d, today = FX_START, date.today()
    while d <= today:
        if d not in have:
            try:
                usd = json.loads(_get(FX_URL.format(d=d.isoformat()), 30))["usd"]
                rows.append({"date": pd.Timestamp(d), **{v: usd.get(k) for k, v in CURRENCIES.items()}})
            except Exception:
                pass                       # a missing snapshot is skipped, not fatal
        d += timedelta(days=7)
    try:                                   # always add today's reading
        usd = json.loads(_get(FX_URL.format(d="latest"), 30))["usd"]
        rows.append({"date": pd.Timestamp(today), **{v: usd.get(k) for k, v in CURRENCIES.items()}})
    except Exception:
        pass
    new = pd.DataFrame(rows).set_index("date") if rows else pd.DataFrame(columns=list(CURRENCIES.values()))
    out = pd.concat([cached, new]) if cached is not None else new
    return out[~out.index.duplicated(keep="last")].sort_index()


def build() -> tuple[pd.DataFrame, pd.DataFrame]:
    cached = pd.read_csv(WEEKLY, parse_dates=["date"]).set_index("date") if WEEKLY.exists() else None
    cols = list(CURRENCIES.values())
    new_cols = cached is not None and bool(set(cols) - set(cached.columns))
    fx = fx_weekly(cached.reindex(columns=cols) if cached is not None else None, backfill=new_cols)
    brent = brent_daily()
    weekly = fx.join(brent.resample("D").ffill().reindex(fx.index, method="ffill"), how="left")
    weekly.round(4).to_csv(WEEKLY)

    # monthly means after the panel ends, spliced onto the panel's own series
    panel = pd.read_csv(PANEL, parse_dates=["date"]).set_index("date")
    end = panel.index.max()
    month = lambda s: s.groupby(s.index.to_period("M")).agg(["mean", "count"])
    b, u = month(brent[brent.index >= "2024-01-01"]), month(fx["ugx_per_usd"])
    rows = []
    for col, m, panel_col in [("brent_crude_usd", b, "brent_crude_usd"), ("exchange_rate", u, "exchange_rate")]:
        overlap = end.to_period("M")
        ratio = panel.loc[end, panel_col] / m.loc[overlap, "mean"] if overlap in m.index else 1.0
        for p, r in m[m.index > overlap].iterrows():
            rows.append({"date": p.to_timestamp(), "column": col, "value": r["mean"] * ratio, "days": int(r["count"])})
    ext = pd.DataFrame(rows).pivot_table(index="date", columns="column", values="value")
    ext["days_fx"] = u.loc[u.index > end.to_period("M"), "count"].values[:len(ext)] if len(ext) else []
    ext.round(4).to_csv(EXT)
    return weekly, ext


if __name__ == "__main__":
    w, e = build()
    print(f"weekly readings {w.index.min():%Y-%m-%d}..{w.index.max():%Y-%m-%d} ({len(w)}); "
          f"monthly extension {', '.join(f'{d:%Y-%m}' for d in e.index)}")
    print(w.tail(3).round(1).to_string())
