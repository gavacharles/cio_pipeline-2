"""
nowcast.py — probability of each outcome bucket for next month's price change.

The market maker opens every contract at these probabilities, and the walk-
forward backtest below is the evidence that they are worth opening at: it
scores them against a climatology baseline (each bucket's historical frequency)
under strict expanding-window evaluation, as P9 does for point forecasts.

Opening probabilities are an equal-weight pool of two forecasts of the
month-on-month % change r_t (all statistics exponentially weighted, 24-month
half-life, as in app/build_dashboard.py):
  1. time-series model:
         mean_t+h = mu + phi^h (r_t - mu) + seasonal[month]
         outcome  = mean_t+h + scale_h * e,   e drawn from the weighted past residuals
  2. recent bucket frequencies (the same weights applied to past outcomes).
On its own the model loses to plain bucket frequencies for lumpy series
(labour, pipes, timber: mostly "unchanged", occasional jumps); the pool beat
plain frequencies in 19 of 24 series x horizon cases over 2021-2026. The
50/50 weight was fixed, not tuned per series.

    predictive_probs(r, target, cuts, horizon) -> np.ndarray (sums to 1)
    model_probs(r, target, cuts, horizon)      -> time-series model alone
    climatology_probs(r, cuts)                 -> baseline: all-history bucket frequencies
    walk_forward(r, cuts, horizon)             -> per-forecast scores
"""
from __future__ import annotations

import numpy as np
import pandas as pd

HALF_LIFE_MONTHS = 24
SEASONAL_MIN_OBS = 60      # seasonal factors only with 5+ years of changes
SEASONAL_SHRINK = 3        # shrink month means toward 0: n_m / (n_m + 3)
MIN_TRAIN = 36
POOL_WEIGHT_MODEL = 0.5


def mom_changes(levels: pd.Series) -> pd.Series:
    """Month-on-month % change on consecutive observed months only."""
    s = levels.astype(float)
    return ((s / s.shift(1) - 1) * 100).dropna()


def _weights(n: int) -> np.ndarray:
    age = np.arange(n)[::-1]
    return 0.5 ** (age / HALF_LIFE_MONTHS)


def _floor(p: np.ndarray, floor: float) -> np.ndarray:
    p = p / p.sum()
    k = len(p)
    floor = min(floor, 0.5 / k)
    return (1 - k * floor) * p + floor


def climatology_probs(r: pd.Series, cuts: list[float]) -> np.ndarray:
    """Each bucket's historical frequency, Laplace-smoothed."""
    idx = np.searchsorted(np.asarray(cuts), r.values, side="right")
    counts = np.bincount(idx, minlength=len(cuts) + 1).astype(float) + 1
    return counts / counts.sum()


def recent_frequency_probs(r: pd.Series, cuts: list[float]) -> np.ndarray:
    """Bucket frequencies, exponentially weighted toward recent months."""
    idx = np.searchsorted(np.asarray(cuts), r.values, side="right")
    counts = np.bincount(idx, weights=_weights(len(r)), minlength=len(cuts) + 1) + 0.5
    return counts / counts.sum()


def fit(r: pd.Series) -> dict:
    x = r.values.astype(float)
    w = _weights(len(x))
    mu = float(np.sum(w * x) / w.sum())
    d = x - mu
    phi = float(np.sum(w[1:] * d[1:] * d[:-1]) / np.sum(w[1:] * d[:-1] ** 2)) if len(x) > 13 else 0.0
    phi = max(-0.5, min(0.8, phi)) if np.isfinite(phi) else 0.0
    seasonal = np.zeros(12)
    if len(x) >= SEASONAL_MIN_OBS:
        months = r.index.month.values - 1
        for m in range(12):
            sel = months == m
            if sel.any():
                seasonal[m] = d[sel].mean() * sel.sum() / (sel.sum() + SEASONAL_SHRINK)
        seasonal -= seasonal.mean()
    fitted = mu + phi * np.r_[0.0, d[:-1]] + seasonal[r.index.month.values - 1]
    resid = x - fitted
    return {"mu": mu, "phi": phi, "seasonal": seasonal, "resid": resid[1:], "w": w[1:],
            "last": float(x[-1])}


def predictive_probs(r: pd.Series, target_month, cuts: list[float], horizon: int = 1,
                     floor: float = 0.02) -> np.ndarray:
    """Probability of each bucket for the change in `target_month`, `horizon` months
    after the last observation in r: the pool the market opens at."""
    pm = model_probs(r, target_month, cuts, horizon, floor=0.0)
    pf = recent_frequency_probs(r, cuts)
    return _floor(POOL_WEIGHT_MODEL * pm + (1 - POOL_WEIGHT_MODEL) * pf, floor)


def model_probs(r: pd.Series, target_month, cuts: list[float], horizon: int = 1,
                floor: float = 0.02, params: dict | None = None) -> np.ndarray:
    """Time-series model alone (see module docstring)."""
    p = params or fit(r)
    m = pd.Timestamp(target_month).month - 1
    mean = p["mu"] + p["phi"] ** horizon * (p["last"] - p["mu"]) + p["seasonal"][m]
    scale = np.sqrt(sum(p["phi"] ** (2 * k) for k in range(horizon)))
    outcomes = mean + scale * p["resid"]
    idx = np.searchsorted(np.asarray(cuts), outcomes, side="right")
    probs = np.bincount(idx, weights=p["w"], minlength=len(cuts) + 1)
    return _floor(probs, floor) if floor > 0 else probs / probs.sum()


def expected_change(probs: np.ndarray, cuts: list[float]) -> float:
    """Rough mean implied by bucket probabilities (outer buckets at edge +/- half a step)."""
    c = np.asarray(cuts, dtype=float)
    step = np.diff(c).mean() if len(c) > 1 else 1.0
    mids = np.r_[c[0] - step / 2, (c[:-1] + c[1:]) / 2, c[-1] + step / 2]
    return float(np.dot(probs, mids))


def walk_forward(r: pd.Series, cuts: list[float], horizon: int = 1, floor: float = 0.02,
                 min_train: int = MIN_TRAIN) -> pd.DataFrame:
    """Expanding-window forecasts: the forecast for r[t] uses only r[: t - horizon + 1]."""
    rows = []
    for t in range(min_train + horizon - 1, len(r)):
        hist = r.iloc[: t - horizon + 1]
        target = r.index[t]
        y = int(np.searchsorted(np.asarray(cuts), r.iloc[t], side="right"))
        pm = predictive_probs(hist, target, cuts, horizon, floor)
        pc = climatology_probs(hist, cuts)
        onehot = np.eye(len(pm))[y]
        rows.append({
            "target": target, "outcome": y,
            "logloss_model": -np.log(pm[y]), "logloss_clim": -np.log(pc[y]),
            "brier_model": float(np.sum((pm - onehot) ** 2)),
            "brier_clim": float(np.sum((pc - onehot) ** 2)),
            "p_outcome_model": pm[y], "top_hit_model": int(np.argmax(pm) == y),
        })
    return pd.DataFrame(rows)


def summarise(scores: pd.DataFrame) -> dict:
    ll_m, ll_c = scores.logloss_model.mean(), scores.logloss_clim.mean()
    d = scores.logloss_clim - scores.logloss_model        # > 0 => model better
    dm = float(d.mean() / (d.std(ddof=1) / np.sqrt(len(d)))) if d.std(ddof=1) > 0 else 0.0
    return {
        "n": len(scores),
        "logloss_model": round(ll_m, 4), "logloss_clim": round(ll_c, 4),
        "log_skill": round(1 - ll_m / ll_c, 4),
        "brier_model": round(scores.brier_model.mean(), 4),
        "brier_clim": round(scores.brier_clim.mean(), 4),
        "mean_p_outcome": round(scores.p_outcome_model.mean(), 4),
        "top_hit_rate": round(scores.top_hit_model.mean(), 4),
        "DM_stat": round(dm, 3),
    }
