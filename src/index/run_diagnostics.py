#!/usr/bin/env python3
"""
Run panel diagnostics for Phase 0:
- coverage heatmap
- missingness map
- Bai-Perron-style structural break scans (dynamic programming)
- unit-root / stationarity tests (ADF + KPSS)
- explicit CIPI rebasing/splice history summary
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from statsmodels.tsa.stattools import adfuller, kpss
import ruptures as rpt


def _read_panel(path: Path) -> pd.DataFrame:
    if path.suffix == ".parquet":
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path, index_col=0)
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, errors="coerce")
    return df.sort_index()


def write_missingness_map(panel: pd.DataFrame, out_png: Path) -> None:
    miss = panel.isna().astype(int).T
    plt.figure(figsize=(16, max(6, 0.32 * miss.shape[0])))
    plt.imshow(miss.values, aspect="auto", interpolation="nearest", cmap="viridis")
    plt.yticks(np.arange(miss.shape[0]), miss.index)
    step = max(1, miss.shape[1] // 12)
    plt.xticks(np.arange(0, miss.shape[1], step), [d.strftime("%Y-%m") for d in panel.index[::step]], rotation=45, ha="right")
    plt.title("Missingness map (1=missing, 0=observed)")
    plt.colorbar(label="Missing")
    plt.tight_layout()
    plt.savefig(out_png, dpi=180)
    plt.close()


def write_coverage_heatmap(panel: pd.DataFrame, out_png: Path, out_csv: Path) -> pd.DataFrame:
    cov = pd.DataFrame(
        {
            "first_obs": panel.apply(lambda s: s.first_valid_index()),
            "last_obs": panel.apply(lambda s: s.last_valid_index()),
            "n_obs": panel.notna().sum(),
            "pct_missing": panel.isna().mean() * 100,
        }
    )
    cov = cov.sort_values("pct_missing", ascending=False)
    cov.to_csv(out_csv)

    mat = cov[["n_obs", "pct_missing"]].copy()
    mat["n_obs"] = mat["n_obs"] / max(1, panel.shape[0])
    plt.figure(figsize=(8, max(6, 0.32 * len(mat))))
    plt.imshow(mat.values, aspect="auto", interpolation="nearest", cmap="magma")
    plt.yticks(np.arange(mat.shape[0]), mat.index)
    plt.xticks([0, 1], ["n_obs_share", "pct_missing"])
    plt.title("Coverage heatmap by series")
    plt.colorbar(label="scaled value")
    plt.tight_layout()
    plt.savefig(out_png, dpi=180)
    plt.close()
    return cov


def _safe_adf(x: pd.Series) -> tuple[float, float] | tuple[None, None]:
    try:
        stat, pval, *_ = adfuller(x.dropna(), autolag="AIC")
        return float(stat), float(pval)
    except Exception:
        return None, None


def _safe_kpss(x: pd.Series) -> tuple[float, float] | tuple[None, None]:
    try:
        stat, pval, *_ = kpss(x.dropna(), nlags="auto", regression="c")
        return float(stat), float(pval)
    except Exception:
        return None, None


def run_unit_root_tests(panel: pd.DataFrame, out_csv: Path) -> pd.DataFrame:
    rows = []
    num = panel.apply(pd.to_numeric, errors="coerce")
    for col in num.columns:
        s = num[col].dropna()
        if len(s) < 24:
            rows.append({"series": col, "n": len(s), "adf_p_level": np.nan, "kpss_p_level": np.nan,
                         "adf_p_diff": np.nan, "kpss_p_diff": np.nan, "stationarity_hint": "insufficient_sample"})
            continue

        adf_stat_l, adf_p_l = _safe_adf(s)
        kpss_stat_l, kpss_p_l = _safe_kpss(s)

        # first difference in logs when valid, else plain difference
        if (s > 0).all():
            d = np.log(s).diff().dropna()
        else:
            d = s.diff().dropna()

        adf_stat_d, adf_p_d = _safe_adf(d)
        kpss_stat_d, kpss_p_d = _safe_kpss(d)

        if (adf_p_l is not None and adf_p_l < 0.05) and (kpss_p_l is not None and kpss_p_l > 0.05):
            hint = "level_stationary"
        elif (adf_p_d is not None and adf_p_d < 0.05) and (kpss_p_d is not None and kpss_p_d > 0.05):
            hint = "difference_stationary"
        else:
            hint = "mixed_or_inconclusive"

        rows.append(
            {
                "series": col,
                "n": len(s),
                "adf_stat_level": adf_stat_l,
                "adf_p_level": adf_p_l,
                "kpss_stat_level": kpss_stat_l,
                "kpss_p_level": kpss_p_l,
                "adf_stat_diff": adf_stat_d,
                "adf_p_diff": adf_p_d,
                "kpss_stat_diff": kpss_stat_d,
                "kpss_p_diff": kpss_p_d,
                "stationarity_hint": hint,
            }
        )

    out = pd.DataFrame(rows).sort_values(["stationarity_hint", "series"])
    out.to_csv(out_csv, index=False)
    return out


def _segment_rss(x: np.ndarray, bkps: list[int]) -> float:
    start = 0
    rss = 0.0
    for b in bkps:
        seg = x[start:b]
        if len(seg) == 0:
            continue
        mu = seg.mean()
        rss += float(((seg - mu) ** 2).sum())
        start = b
    return rss


def run_bai_perron_style_breaks(panel: pd.DataFrame, out_csv: Path, max_breaks: int = 3, min_size: int = 12) -> pd.DataFrame:
    rows = []
    num = panel.apply(pd.to_numeric, errors="coerce")
    for col in num.columns:
        s = num[col].dropna()
        n = len(s)
        if n < (min_size * 3):
            rows.append({"series": col, "n": n, "selected_breaks": 0, "break_dates": "", "method": "insufficient_sample"})
            continue

        x = s.values.astype(float)
        algo = rpt.Dynp(model="l2", min_size=min_size, jump=1).fit(x)

        best = None
        for m in range(0, max_breaks + 1):
            try:
                bkps = algo.predict(n_bkps=m)
            except Exception:
                continue
            rss = _segment_rss(x, bkps)
            k = m + 1
            bic = n * np.log(max(rss / n, 1e-12)) + k * np.log(n)
            if (best is None) or (bic < best["bic"]):
                best = {"m": m, "bkps": bkps, "bic": float(bic), "rss": float(rss)}

        if best is None:
            rows.append({"series": col, "n": n, "selected_breaks": 0, "break_dates": "", "method": "failed"})
            continue

        # bkps includes the terminal point n
        cut_ix = best["bkps"][:-1]
        break_dates = [s.index[i - 1].strftime("%Y-%m-%d") for i in cut_ix if i > 0 and i <= n]

        rows.append(
            {
                "series": col,
                "n": n,
                "selected_breaks": int(best["m"]),
                "break_dates": ";".join(break_dates),
                "bic": best["bic"],
                "rss": best["rss"],
                "method": "dynp_l2_bic (Bai-Perron-style)"
            }
        )

    out = pd.DataFrame(rows).sort_values(["selected_breaks", "series"], ascending=[False, True])
    out.to_csv(out_csv, index=False)
    return out


def write_rebasing_history(splice_log_path: Path, out_csv: Path, out_md: Path) -> pd.DataFrame:
    slog = pd.read_csv(splice_log_path)
    slog["splice_factor"] = pd.to_numeric(slog["splice_factor"], errors="coerce")
    hist = (
        slog.assign(
            no_overlap=slog["note"].fillna("").str.contains("NO OVERLAP", case=False),
            overlap_n=slog["note"].fillna("").str.extract(r"overlap=(\d+)")[0].astype(float),
        )
        .groupby("series_code", as_index=False)
        .agg(
            n_links=("older", "count"),
            n_no_overlap=("no_overlap", "sum"),
            min_splice_factor=("splice_factor", "min"),
            max_splice_factor=("splice_factor", "max"),
            median_overlap=("overlap_n", "median"),
        )
        .sort_values(["n_no_overlap", "series_code"], ascending=[False, True])
    )
    hist.to_csv(out_csv, index=False)

    flagged = hist[hist["n_no_overlap"] > 0]
    lines = [
        "# CIPI Rebasing / Splice History",
        "",
        f"Total series with splice links: {len(hist)}",
        f"Series with at least one NO OVERLAP flag: {len(flagged)}",
        "",
        "## Series flagged for manual review",
        "",
    ]
    if flagged.empty:
        lines.append("None.")
    else:
        lines.append("series_code,n_links,n_no_overlap,min_splice_factor,max_splice_factor,median_overlap")
        for _, r in flagged.iterrows():
            lines.append(
                f"{r['series_code']},{int(r['n_links'])},{int(r['n_no_overlap'])},"
                f"{r['min_splice_factor'] if pd.notna(r['min_splice_factor']) else ''},"
                f"{r['max_splice_factor'] if pd.notna(r['max_splice_factor']) else ''},"
                f"{r['median_overlap'] if pd.notna(r['median_overlap']) else ''}"
            )

    out_md.write_text("\n".join(lines), encoding="utf-8")
    return hist


def main() -> None:
    ap = argparse.ArgumentParser(description="Run panel diagnostics and rebasing documentation.")
    ap.add_argument("--panel", default="data/processed/panel_v1.0.parquet")
    ap.add_argument("--splice-log", default="data/processed/splice_log.csv")
    ap.add_argument("--out-dir", default="data/processed/diagnostics")
    args = ap.parse_args()

    panel_path = Path(args.panel)
    splice_log_path = Path(args.splice_log)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    panel = _read_panel(panel_path)

    write_missingness_map(panel, out_dir / "missingness_map.png")
    cov = write_coverage_heatmap(panel, out_dir / "coverage_heatmap.png", out_dir / "coverage_metrics.csv")
    ur = run_unit_root_tests(panel, out_dir / "unit_root_stationarity_tests.csv")
    br = run_bai_perron_style_breaks(panel, out_dir / "bai_perron_style_breaks.csv")
    rb = write_rebasing_history(splice_log_path, out_dir / "rebasing_history_summary.csv", out_dir / "rebasing_history.md")

    summary = {
        "panel_shape": [int(panel.shape[0]), int(panel.shape[1])],
        "coverage_file": str((out_dir / "coverage_metrics.csv")),
        "missingness_map": str((out_dir / "missingness_map.png")),
        "coverage_heatmap": str((out_dir / "coverage_heatmap.png")),
        "unit_root_tests": str((out_dir / "unit_root_stationarity_tests.csv")),
        "break_scans": str((out_dir / "bai_perron_style_breaks.csv")),
        "rebasing_history": str((out_dir / "rebasing_history_summary.csv")),
        "n_series_stationarity": int(len(ur)),
        "n_series_break_scan": int(len(br)),
        "n_series_rebasing": int(len(rb)),
    }
    (out_dir / "diagnostics_manifest.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
