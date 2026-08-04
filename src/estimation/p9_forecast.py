"""
p9_forecast.py  —  Paper P9 (capstone) starter.
Network-augmented forecasting of the CIPI. Tests P9's core question: does
augmenting a forecaster with time-varying network features (centralities from P5,
spillover receipts from P4) beat baselines under STRICT walk-forward (expanding-
window) evaluation? Diebold-Mariano tests report whether a gain is meaningful.

The public API is:
    make_features(panel)               -> feature DataFrame (target + lags + network)
    walk_forward(df, use_network=...)  -> (errors, actuals, preds) with no leakage
    diebold_mariano(e1, e2)            -> DM statistic on squared-error loss

torch is OPTIONAL. The default forecaster is a ridge-regression on lags (+network),
which keeps the reviewer-critical walk-forward harness fully runnable without a GPU;
swap in a GRU where torch is available.

Inputs : data/processed/panel_v1.0.parquet  (+ optional P4/P5 feature CSVs)
Outputs: p9_forecast_metrics.csv
"""
from __future__ import annotations
import numpy as np, pandas as pd
from pathlib import Path

TARGET = "CIPI_ALL"


def make_features(panel: pd.DataFrame, n_lags: int = 3) -> pd.DataFrame:
    """Build a supervised frame: target + own lags + (proxy) network features.
    Network features here are rolling cross-material dispersion and mean pairwise
    correlation — stand-ins for the P4 spillover-receipt / P5 centrality series,
    which drop in directly as extra columns when available."""
    y = pd.to_numeric(panel[TARGET], errors="coerce")
    df = pd.DataFrame({"y": y})
    for L in range(1, n_lags + 1):
        df[f"lag{L}"] = y.shift(L)
    mats = [c for c in panel.columns if c.isupper() and not c.startswith("CIPI")
            and c not in ("exchange_rate",)]
    M = panel[mats].apply(pd.to_numeric, errors="coerce")
    ret = np.log(M).diff()
    # proxy network features (replace with real P4/P5 outputs when present)
    df["net_dispersion"] = ret.std(axis=1).shift(1)
    df["net_meancorr"] = ret.rolling(6).corr().groupby(level=0).mean().mean(axis=1).shift(1) \
        if len(mats) > 1 else 0.0
    return df.dropna()


def _fit_predict(train: pd.DataFrame, test_row: pd.Series, cols: list[str]) -> float:
    from sklearn.linear_model import Ridge
    Xtr, ytr = train[cols].values, train["y"].values
    model = Ridge(alpha=1.0).fit(Xtr, ytr)
    return float(model.predict(test_row[cols].values.reshape(1, -1))[0])


def walk_forward(df: pd.DataFrame, use_network: bool = True, min_train: int = 36):
    """Expanding-window one-step-ahead forecasts. No look-ahead: features at time t
    use only information dated <= t-1 (guaranteed by the shifts in make_features)."""
    base = [c for c in df.columns if c.startswith("lag")]
    net = ["net_dispersion", "net_meancorr"] if use_network else []
    cols = base + [c for c in net if c in df.columns]
    errs, actuals, preds = [], [], []
    for t in range(min_train, len(df)):
        train = df.iloc[:t]
        test_row = df.iloc[t]
        pred = _fit_predict(train, test_row, cols)
        actual = float(test_row["y"])
        preds.append(pred); actuals.append(actual); errs.append(actual - pred)
    return np.array(errs), np.array(actuals), np.array(preds)


def diebold_mariano(e1: np.ndarray, e2: np.ndarray) -> dict:
    d = e1**2 - e2**2
    if np.allclose(d.var(), 0):
        return {"DM_stat": 0.0, "mean_loss_diff": 0.0, "note": "identical losses"}
    dm = d.mean() / (d.std(ddof=1) / np.sqrt(len(d)))
    return {"DM_stat": float(dm), "mean_loss_diff": float(d.mean())}


if __name__ == "__main__":
    panel = pd.read_parquet("data/processed/panel_v1.0.parquet")
    df = make_features(panel)
    e_net, a, p_net = walk_forward(df, use_network=True)
    e_base, _, p_base = walk_forward(df, use_network=False)
    rmse = lambda e: float(np.sqrt(np.mean(e**2)))
    dm = diebold_mariano(e_base, e_net)
    out = pd.DataFrame([
        {"model": "lags_only",      "RMSE": rmse(e_base), "MAE": float(np.mean(np.abs(e_base)))},
        {"model": "lags+network",   "RMSE": rmse(e_net),  "MAE": float(np.mean(np.abs(e_net)))},
        {"model": "DM base_vs_net", "RMSE": np.nan, "MAE": np.nan, **dm},
    ])
    out.to_csv("p9_forecast_metrics.csv", index=False)
    print("P9 done. Does adding network features help?")
    print(out.to_string(index=False))
    print("\nNegative DM_stat => network model has lower squared-error loss "
          "(improvement); check significance against +/-1.96.")
