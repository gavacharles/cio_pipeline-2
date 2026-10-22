"""
cost_pressure.py — imported-input cost pressure for countries without a usable official index.

Most of a construction basket's short-run movement in these economies comes from two
things everybody can observe weekly: fuel (oil in local currency) and imported materials
(the exchange rate). The indicator is

    pressure_t = W_FUEL * dlog(Brent in local currency)_t + W_IMPORT * dlog(local per USD)_t

in % per month, with the rest of the basket (local materials, labour) held flat. It is an
indicator of pressure, NOT a price index. Weights follow the official baskets seen in the
pilot countries: fuel and transport ~10% (Kenya 9.6%, Uganda diesel 8.6%) and imported or
import-priced materials ~40% (steel, cement inputs, pipes, paint, fittings).

Forecasts: future monthly driver changes are drawn in 3-month blocks from the last five years
(joint, so oil and currency moves keep their co-movement); months already observed are fixed.

    pressure_history(country)               -> monthly % series
    forecast(country, horizons=(3, 6))      -> {h: (median, p10, p90)} cumulative %
    validate(country, official_changes)     -> correlation with an official index
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
W_FUEL, W_IMPORT = 0.10, 0.40
LOOKBACK_MONTHS = 60
BLOCK = 3


def _monthly_drivers(fx_col: str) -> pd.DataFrame:
    """Monthly averages of local currency per USD (IMF history + weekly snapshots) and Brent (USD)."""
    imf = pd.read_csv(ROOT / "data" / "raw" / "fx_imf_monthly.csv", parse_dates=["date"]).set_index("date")
    wk = pd.read_csv(ROOT / "data" / "raw" / "weekly_drivers.csv", parse_dates=["date"]).set_index("date")
    fx_w = wk[fx_col].groupby(wk.index.to_period("M")).mean() if fx_col in wk else pd.Series(dtype=float)
    fx_w.index = fx_w.index.to_timestamp() if len(fx_w) else fx_w.index
    fx = imf[fx_col] if fx_col in imf else pd.Series(dtype=float)
    both = pd.concat([fx, fx_w], axis=1).dropna()
    ratio = (both.iloc[:, 0] / both.iloc[:, 1]).tail(6).mean() if len(both) else 1.0
    fx = fx.combine_first(fx_w * ratio) if len(fx) else fx_w
    panel = pd.read_csv(ROOT / "data" / "processed" / "panel_v1.0_extended.csv", parse_dates=["date"]).set_index("date")
    brent = panel["brent_crude_usd"]
    ext = ROOT / "data" / "processed" / "macro_extension_monthly.csv"
    if ext.exists():
        brent = brent.combine_first(pd.read_csv(ext, parse_dates=["date"]).set_index("date")["brent_crude_usd"])
    return pd.DataFrame({"fx": fx, "brent": brent}).dropna()


def pressure_history(fx_col: str) -> pd.Series:
    d = _monthly_drivers(fx_col)
    dl = 100 * np.log(d).diff()
    return (W_FUEL * (dl["brent"] + dl["fx"]) + W_IMPORT * dl["fx"]).dropna().rename("pressure_pct")


def forecast(fx_col: str, horizons=(3, 6), n_paths: int = 4000, seed: int = 0) -> dict:
    """Cumulative % pressure over the next h months after the latest observed month."""
    p = pressure_history(fx_col).tail(LOOKBACK_MONTHS).values
    if len(p) < 2 * BLOCK:
        return {}
    rng = np.random.default_rng(seed)
    H = max(horizons)
    nb = int(np.ceil(H / BLOCK))
    starts = rng.integers(0, len(p) - BLOCK + 1, size=(n_paths, nb))
    draws = p[(starts[..., None] + np.arange(BLOCK)).reshape(n_paths, -1)[:, :H]]
    cum = np.cumsum(draws, axis=1)
    return {h: tuple(np.percentile(cum[:, h - 1], [50, 10, 90])) for h in horizons}


def validate(fx_col: str, official: pd.Series, window: int = 3) -> dict:
    """Correlation of `window`-month changes: pressure (leading by 0..2 months) vs an official index."""
    pr = pressure_history(fx_col).rolling(window).sum()
    off = (100 * np.log(official.dropna()).diff(window)).dropna()
    out = {}
    for lag in (0, 1, 2):
        j = pd.concat([pr.shift(lag), off], axis=1).dropna()
        out[lag] = (round(float(j.corr().iloc[0, 1]), 2), len(j)) if len(j) > 12 else (None, len(j))
    return out
