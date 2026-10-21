#!/usr/bin/env python3
"""
run_forecast.py — structural CIPI forecaster: structure check, backtest, forecast, stability.

    python src/forecast/run_forecast.py structure   # does the published index rebuild from its weights?
    python src/forecast/run_forecast.py backtest    # walk-forward vs no-change, drift, direct AR(1)
    python src/forecast/run_forecast.py forecast    # paths + fan bands, every scenario, 18 months
    python src/forecast/run_forecast.py stability   # do the pass-through estimates drift over time?

Outputs (data/processed/forecast/):
    structure_weights.csv, structure_check.csv, contributions_12m.csv
    backtest_errors.csv, backtest_metrics.csv, interval_calibration.csv
    forecast_paths.csv, forecast_components.csv, forecast_contributions.csv
    coefficients.csv, stability.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from index_structure import read_release, latest_weighted_release   # noqa: E402
from model import ForecastModel, primitives, load_macro, load_policy_events  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "processed" / "forecast"
CFG = ROOT / "config" / "forecast_model.yaml"
SHEETS = ["ALL", "BUILDINGS", "CIVIL", "SPECIALISED"]
KEY_COMPONENTS = ["diesel", "cement", "high tensile steel bars", "labour", "unpublished materials (all)"]
HORIZONS = [1, 3, 6, 12]
BAND = (10, 90)                       # 80% interval
HALF_LIFE = 24


def load(args):
    cfg = yaml.safe_load(open(args.config or CFG, encoding="utf-8"))
    release = Path(args.release) if args.release else latest_weighted_release(
        [ROOT / "data" / "raw", ROOT / "data" / "raw" / "ubos_cipi_downloads"])
    structure = read_release(release)
    macro = load_macro(cfg, ROOT)
    OUT.mkdir(parents=True, exist_ok=True)
    return cfg, structure, macro


# ------------------------------------------------------------- structure --
def cmd_structure(args) -> None:
    cfg, s, _ = load(args)
    w = pd.DataFrame(s.weights).rename_axis("component")
    w.to_csv(OUT / "structure_weights.csv")
    chk = pd.Series(s.verify(), name="max_abs_error_index_points").rename_axis("sheet")
    chk.to_csv(OUT / "structure_check.csv")
    end = s.levels.index.max()
    con = s.contributions("ALL", end - pd.DateOffset(months=12), end)
    con.to_csv(OUT / "contributions_12m.csv")
    print(f"release {s.source_file}: {s.levels.shape[1]} components, {len(s.levels)} months "
          f"({s.levels.index.min():%Y-%m}..{end:%Y-%m})")
    print("rebuild error (index points):", {k: f"{v:.1e}" for k, v in s.verify().items()})
    hid = {k: round(v[f"unpublished materials ({k.lower()})"], 1) for k, v in s.weights.items()}
    print("unpublished materials weight per sheet:", hid)
    print(f"\ncontributions to the ALL index change {end - pd.DateOffset(months=12):%Y-%m} -> {end:%Y-%m} "
          f"({s.published['ALL'].iloc[-13]:.2f} -> {s.published['ALL'].iloc[-1]:.2f}):")
    print(con.round(3).iloc[::-1].head(8).to_string())


# -------------------------------------------------------------- backtest --
def _ew_mean(x: np.ndarray) -> float:
    w = 0.5 ** (np.arange(len(x))[::-1] / HALF_LIFE)
    return float((w * x).sum() / w.sum())


def _ar1_path(r: np.ndarray, H: int) -> np.ndarray:
    y, x = r[1:], r[:-1]
    b = np.polyfit(x, y, 1)
    out, prev = [], r[-1]
    for _ in range(H):
        prev = b[1] + b[0] * prev
        out.append(prev)
    return np.cumsum(out)


def _target_levels(s, name):
    return s.published[name] if name in s.published else s.levels[name]


def cmd_backtest(args) -> None:
    cfg, s, macro = load(args)
    prim_all = primitives(macro, cfg)
    dates = s.levels.index
    min_train = cfg["model"]["min_train_months"]
    Hmax = max(HORIZONS)
    targets = SHEETS + KEY_COMPONENTS
    rows = []
    origins = dates[min_train:-1]
    for k, origin in enumerate(origins):
        m = ForecastModel(cfg).fit(s, macro, origin)
        H = min(Hmax, len(dates) - dates.get_loc(origin) - 1)
        P = m.simulate(H, n_paths=args.paths, seed=k)
        future = prim_all.loc[origin:].iloc[1:H + 1]
        Pex = m.simulate(H, n_paths=200, seed=k, macro_path=future[m.prim_cols].values) if len(future) == H else None
        cols = list(s.levels.columns)
        for name in targets:
            if name in SHEETS:
                sim, ex = m.aggregate_paths(P, name), (m.aggregate_paths(Pex, name) if Pex is not None else None)
            else:
                j = cols.index(name)
                sim, ex = P[:, :, j], (Pex[:, :, j] if Pex is not None else None)
            lv = _target_levels(s, name)
            base = float(lv.loc[origin])
            r_hist = 100 * np.log(lv.loc[:origin]).diff().dropna().values
            ar = _ar1_path(r_hist, H)
            for h in HORIZONS:
                if h > H:
                    continue
                actual = 100 * np.log(lv.iloc[dates.get_loc(origin) + h] / base)
                cum = 100 * np.log(sim[:, h - 1] / base)
                lo, hi = np.percentile(cum, BAND)
                rows.append({
                    "origin": origin, "target": name, "h": h, "actual": actual,
                    "structural": float(cum.mean()), "lo": lo, "hi": hi,
                    "structural_expost": float(100 * np.log(ex[:, h - 1] / base).mean()) if ex is not None else np.nan,
                    "no_change": 0.0, "drift": h * _ew_mean(r_hist), "ar1": float(ar[h - 1]),
                })
        if (k + 1) % 10 == 0:
            print(f"  {k + 1}/{len(origins)} origins")
    err = pd.DataFrame(rows)
    err.to_csv(OUT / "backtest_errors.csv", index=False)
    met = backtest_metrics(err)
    met.to_csv(OUT / "backtest_metrics.csv", index=False)
    cal = interval_calibration(err)
    cal.to_csv(OUT / "interval_calibration.csv", index=False)
    show = met[met.target.isin(["ALL"] + KEY_COMPONENTS[:3])]
    print(show.to_string(index=False))
    print("\nrel_* = RMSE / RMSE(drift) (< 1 beats drift). DM_vs_drift < -1.96 => structural significantly better.")
    print("coverage80 should be close to 0.80.")
    print("\ninterval calibration (index sheets pooled): forecast bands are widened by `scale`")
    print(cal.to_string(index=False))


def _dm(e1: np.ndarray, e2: np.ndarray, h: int) -> float:
    """Diebold-Mariano on squared errors with Newey-West variance (h-1 lags, overlapping h-step errors)."""
    d = e1 ** 2 - e2 ** 2
    n = len(d)
    if n < 8 or d.std() == 0:
        return np.nan
    dc = d - d.mean()
    v = dc @ dc / n
    for L in range(1, h):
        v += 2 * (1 - L / h) * (dc[L:] @ dc[:-L]) / n
    return float(d.mean() / np.sqrt(max(v, 1e-12) / n))


def backtest_metrics(err: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (t, h), g in err.groupby(["target", "h"], sort=False):
        rmse = {k: float(np.sqrt(((g[k] - g.actual) ** 2).mean()))
                for k in ["structural", "structural_expost", "no_change", "drift", "ar1"]}
        rows.append({
            "target": t, "h": h, "n": len(g),
            "rmse_structural": round(rmse["structural"], 3), "rmse_drift": round(rmse["drift"], 3),
            "rel_structural": round(rmse["structural"] / rmse["drift"], 3),
            "rel_no_change": round(rmse["no_change"] / rmse["drift"], 3),
            "rel_ar1": round(rmse["ar1"] / rmse["drift"], 3),
            "rel_expost": round(rmse["structural_expost"] / rmse["drift"], 3),
            "DM_vs_drift": round(_dm((g.structural - g.actual).values, (g.drift - g.actual).values, h), 2),
            "coverage80": round(((g.actual >= g.lo) & (g.actual <= g.hi)).mean(), 2),
        })
    return pd.DataFrame(rows)


def interval_calibration(err: pd.DataFrame) -> pd.DataFrame:
    """Horizon-specific factor that widens the simulated 80% band around the median until it
    covers 80% of backtest outcomes for the published indices (never narrows it)."""
    rows = []
    for h, g in err[err.target.isin(SHEETS)].groupby("h"):
        mid = g.structural
        half = np.where(g.actual >= mid, g.hi - mid, mid - g.lo)
        z = np.abs(g.actual - mid) / np.maximum(half, 1e-9)
        scale = max(1.0, float(np.quantile(z, 0.8)))
        rows.append({"h": h, "n": len(g), "coverage_raw": round(float((z <= 1).mean()), 3),
                     "scale": round(scale, 3), "coverage_calibrated": round(float((z <= scale).mean()), 3)})
    return pd.DataFrame(rows)


def _band_scale(H: int) -> np.ndarray:
    """Calibration factor for horizons 1..H (interpolated; held flat beyond the last tested h)."""
    f = OUT / "interval_calibration.csv"
    if not f.exists():
        print("note: no interval_calibration.csv yet (run backtest); bands are uncalibrated")
        return np.ones(H)
    cal = pd.read_csv(f)
    return np.interp(np.arange(1, H + 1), cal.h, cal.scale)


# -------------------------------------------------------------- forecast --
def cmd_forecast(args) -> None:
    cfg, s, macro = load(args)
    m = ForecastModel(cfg).fit(s, macro)
    m.events = load_policy_events(cfg, ROOT)
    m.coefficients().to_csv(OUT / "coefficients.csv", index=False)
    H = args.horizon
    months = pd.date_range(m.origin + pd.DateOffset(months=1), periods=H, freq="MS")
    scale = _band_scale(H)
    rows, comp_rows = [], []
    for scen in cfg["scenarios"]:
        P = m.simulate(H, scenario=scen)
        for sheet in SHEETS:
            A = m.aggregate_paths(P, sheet)
            q = np.percentile(A, [10, 50, 90], axis=0)
            q[0] = q[1] - scale * (q[1] - q[0])          # calibrated 80% band
            q[2] = q[1] + scale * (q[2] - q[1])
            base = s.published[sheet].iloc[-1]
            for i, d in enumerate(months):
                rows.append({"scenario": scen, "index": sheet, "month": d.strftime("%Y-%m"),
                             "p10": q[0, i], "median": q[1, i], "p90": q[2, i], "mean": A[:, i].mean(),
                             "change_vs_origin_pct": (q[1, i] / base - 1) * 100})
        if scen == "baseline":
            med = np.median(P, axis=0)
            for j, c in enumerate(s.levels.columns):
                for i, d in enumerate(months):
                    comp_rows.append({"component": c, "month": d.strftime("%Y-%m"), "median": med[i, j],
                                      "p10": np.percentile(P[:, i, j], 10), "p90": np.percentile(P[:, i, j], 90)})
            end_levels = pd.DataFrame(med, index=months, columns=s.levels.columns)
            w = pd.Series(s.weights["ALL"])
            a, b = s.levels.iloc[-1][w.index], end_levels.iloc[min(11, H - 1)][w.index]
            con = pd.DataFrame({"weight": w, "change_pct": (b / a - 1) * 100,
                                "contribution_pp": w * (b - a) / float((w * a).sum()) * 100})
            con.sort_values("contribution_pp").to_csv(OUT / "forecast_contributions.csv")
    out = pd.DataFrame(rows).round(3)
    out.to_csv(OUT / "forecast_paths.csv", index=False)
    pd.DataFrame(comp_rows).round(3).to_csv(OUT / "forecast_components.csv", index=False)
    print(f"origin {m.origin:%Y-%m} (latest release on file: {s.source_file}); overall index "
          f"{s.published['ALL'].iloc[-1]:.2f}\n")
    for h in (3, 6, 12, H):
        d = months[h - 1].strftime("%Y-%m")
        t = out[(out["index"] == "ALL") & (out.month == d)]
        print(f"overall index, {d} (h={h}):")
        for _, r in t.iterrows():
            print(f"  {r.scenario:<20} median {r['median']:7.2f}  ({r.change_vs_origin_pct:+5.2f}%)   "
                  f"80% band {r.p10:7.2f} - {r.p90:7.2f}")


# ------------------------------------------------------------- stability --
def cmd_stability(args) -> None:
    cfg, s, macro = load(args)
    dates = s.levels.index
    rows = []
    for origin in dates[cfg["model"]["min_train_months"]::3]:
        co = ForecastModel(cfg).fit(s, macro, origin).coefficients()
        co["origin"] = origin
        rows.append(co)
    st = pd.concat(rows)
    st.to_csv(OUT / "stability.csv", index=False)
    # long-run pass-through: (lag0 + lag1-3) / (1 - own_lag), per driver
    piv = st.pivot_table(index=["origin", "component"], columns="term", values="coef")
    out = []
    for drv in cfg["drivers"]:
        cols = [c for c in (f"{drv}_lag0", f"{drv}_lag1-3") if c in piv.columns]
        lr = piv[cols].sum(axis=1, min_count=1) / (1 - piv["own_lag"])
        out.append(lr.rename(drv))
    lr = pd.concat(out, axis=1).reset_index()
    focus = {"diesel": "oil", "diesel ": "fx", "cement": "fx", "high tensile steel bars": "ore",
             "labour": "cpi", "unpublished materials (all)": "cpi"}
    print("long-run pass-through (% response to a sustained 1% move), by estimation end date:")
    for comp, drv in focus.items():
        ser = lr[lr.component == comp.strip()].set_index("origin")[drv]
        pre = ser[ser.index < "2022-03-01"]
        print(f"  {comp.strip():<28} <- {drv:<4} range {ser.min():+.3f}..{ser.max():+.3f}   "
              f"pre-2022 mean {pre.mean():+.3f}   latest {ser.iloc[-1]:+.3f}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--release", help="weighted CIPI workbook (default: newest in data/raw)")
    ap.add_argument("--config", help="model config (default: config/forecast_model.yaml)")
    ap.add_argument("--out", help="output folder (default: data/processed/forecast)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("structure").set_defaults(fn=cmd_structure)
    p = sub.add_parser("backtest"); p.add_argument("--paths", type=int, default=500); p.set_defaults(fn=cmd_backtest)
    p = sub.add_parser("forecast"); p.add_argument("--horizon", type=int, default=18); p.set_defaults(fn=cmd_forecast)
    sub.add_parser("stability").set_defaults(fn=cmd_stability)
    args = ap.parse_args()
    if args.out:
        global OUT
        OUT = Path(args.out)
    args.fn(args)


if __name__ == "__main__":
    main()
