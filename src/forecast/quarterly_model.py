"""
quarterly_model.py — compact forecaster for quarterly construction indices (Kenya, KNBS).

KNBS gives ~26 quarters (Q4 2019 onward), too few for the monthly structural model.
So each series gets one small equation on its quarter-on-quarter % change:

    r_t = a + rho * r_t-1 + sum_d ( b0_d * x_d,t + b1_d * x_d,t-1 ) + e_t

with drivers x = 100*dlog of quarterly averages of the local currency per USD (fx) and
of Brent in local currency (oil), ridge-shrunk (standardised drivers, alpha below) so
26 points cannot produce wild coefficients. Forecasts simulate future driver changes by
resampling past quarters jointly with the series residuals, EXCEPT for quarters whose
drivers are already observed (daily Brent, weekly/monthly FX), which are fixed — this is
what makes the weekly note informative between KNBS releases.

    QuarterlyModel(alpha).fit(levels, drivers, origin)
        .simulate(H, known_drivers, n_paths) -> level paths [P, H]
    backtest(levels, drivers, ...)          -> errors vs drift / no-change
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DRIVERS = ["fx", "oil"]


def quarterly_drivers(currency_col: str, end: pd.Timestamp | None = None) -> pd.DataFrame:
    """Quarterly 100*dlog of FX (local per USD) and Brent in local currency, from the IMF
    monthly history spliced with weekly snapshots, and daily Brent (EIA via weekly file +
    panel). Partial quarters use the months observed so far (column `months`)."""
    fx_m = pd.read_csv(ROOT / "data" / "raw" / "fx_imf_monthly.csv", parse_dates=["date"]).set_index("date")[currency_col]
    wk = pd.read_csv(ROOT / "data" / "raw" / "weekly_drivers.csv", parse_dates=["date"]).set_index("date")
    fx_w = wk[currency_col].groupby(wk.index.to_period("M")).mean()
    fx_w.index = fx_w.index.to_timestamp()
    ratio = (fx_m / fx_w).dropna().tail(6).mean() if len((fx_m / fx_w).dropna()) else 1.0
    fx = fx_m.combine_first(fx_w * ratio)
    panel = pd.read_csv(ROOT / "data" / "processed" / "panel_v1.0_extended.csv", parse_dates=["date"]).set_index("date")
    brent = panel["brent_crude_usd"]
    ext = ROOT / "data" / "processed" / "macro_extension_monthly.csv"
    if ext.exists():
        brent = brent.combine_first(pd.read_csv(ext, parse_dates=["date"]).set_index("date")["brent_crude_usd"])
    m = pd.DataFrame({"fx": fx, "oil": brent * fx}).dropna()
    if end is not None:
        m = m.loc[:end]
    q = m.groupby(m.index.to_period("Q")).agg(["mean", "count"])
    lv = pd.DataFrame({c: q[(c, "mean")] for c in DRIVERS})
    out = 100 * np.log(lv).diff()
    out["months"] = q[("fx", "count")]
    out.index = out.index.to_timestamp()
    return out.dropna(subset=DRIVERS)


class QuarterlyModel:
    def __init__(self, alpha: float = 4.0, drivers: list[str] | None = None):
        self.alpha, self.drivers = alpha, drivers or DRIVERS

    def _X(self, r: pd.Series, D: pd.DataFrame) -> pd.DataFrame:
        cols = {"own": r.shift(1)}
        for d in self.drivers:
            cols[f"{d}_0"], cols[f"{d}_1"] = D[d], D[d].shift(1)
        return pd.DataFrame(cols)

    def fit(self, levels: pd.Series, D: pd.DataFrame, origin=None) -> "QuarterlyModel":
        lv = levels.dropna()
        if origin is not None:
            lv = lv.loc[:pd.Timestamp(origin)]
        r = 100 * np.log(lv).diff()
        r = r[r.index.to_series().diff().dt.days.fillna(92).between(85, 95)]   # skip gaps (e.g. Q4-2021)
        X = self._X(r, D).reindex(r.index)
        ok = X.notna().all(axis=1) & r.notna()
        Xf, y = X[ok].values, r[ok].values
        mu, sd = Xf.mean(0), Xf.std(0) + 1e-9
        Z = np.c_[np.ones(len(Xf)), (Xf - mu) / sd]
        pen = np.full(Z.shape[1], self.alpha); pen[0] = 0
        b = np.linalg.solve(Z.T @ Z + np.diag(pen), Z.T @ y)
        self.coef = b[1:] / sd
        self.coef[0] = float(np.clip(self.coef[0], -0.5, 0.8))
        self.intercept = float(b[0] - (b[1:] / sd) @ mu)
        self.names = list(X.columns)
        self.resid = pd.Series(y - (self.intercept + Xf @ self.coef), index=r[ok].index)
        self.last_level, self.last_r = float(lv.iloc[-1]), float(r.dropna().iloc[-1])
        self.origin = lv.index[-1]
        self.D = D
        return self

    def simulate(self, H: int, n_paths: int = 2000, known: pd.DataFrame | None = None, seed: int = 0):
        """Level paths [P, H]. `known` = driver changes already observed for future quarters."""
        rng = np.random.default_rng(seed)
        hist = self.D.loc[self.resid.index, self.drivers].values
        idx = rng.integers(0, len(self.resid), size=(n_paths, H))
        drv = hist[idx]                                       # [P, H, d] resampled driver quarters
        e = self.resid.values[idx]                            # residuals from the same quarters
        futq = pd.date_range(self.origin + pd.DateOffset(months=3), periods=H, freq="QS-JAN")
        if known is not None:
            for h, q in enumerate(futq):
                if q in known.index:
                    for j, d in enumerate(self.drivers):
                        if pd.notna(known.loc[q, d]):
                            drv[:, h, j] = known.loc[q, d]
        prev_x = np.repeat(self.D.loc[self.origin, self.drivers].values[None].astype(float), n_paths, axis=0)
        prev_r = np.full(n_paths, self.last_r)
        lvl = np.full(n_paths, np.log(self.last_level))
        out = np.empty((n_paths, H))
        for h in range(H):
            feats = [prev_r]
            for j in range(len(self.drivers)):
                feats += [drv[:, h, j], prev_x[:, j]]
            r = self.intercept + np.stack(feats, axis=1) @ self.coef + e[:, h]
            lvl = lvl + r / 100
            out[:, h] = np.exp(lvl)
            prev_r, prev_x = r, drv[:, h, :]
        return out, futq


def backtest(levels: pd.Series, D: pd.DataFrame, min_train: int = 12, horizons=(1, 2), alpha: float = 4.0,
             drivers: list[str] | None = None) -> pd.DataFrame:
    """Walk-forward: refit at each origin; drivers ex ante (resampled), so no look-ahead."""
    lv = levels.dropna()
    rows = []
    for k in range(min_train, len(lv) - 1):
        origin = lv.index[k]
        try:
            m = QuarterlyModel(alpha, drivers).fit(lv, D.loc[:origin], origin)
        except Exception:
            continue
        paths, futq = m.simulate(max(horizons), n_paths=1000, seed=k)
        r_hist = 100 * np.log(lv.loc[:origin]).diff().dropna()
        w = 0.5 ** (np.arange(len(r_hist))[::-1] / 8)
        drift = float((w * r_hist).sum() / w.sum())
        for h in horizons:
            q = futq[h - 1]
            if q not in lv.index:
                continue
            actual = 100 * np.log(lv[q] / lv[origin])
            sim = 100 * np.log(paths[:, h - 1] / lv[origin])
            lo, hi = np.percentile(sim, [10, 90])
            rows.append({"origin": origin, "h": h, "actual": actual, "model": float(np.median(sim)),
                         "drift": drift * h, "no_change": 0.0, "covered": lo <= actual <= hi})
    return pd.DataFrame(rows)
