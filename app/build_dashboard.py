#!/usr/bin/env python3
"""
build_dashboard.py — assemble the CiO Phase 0 Explorer and Projection Workbench.

Reads the pipeline's processed outputs (panel, audit trail, diagnostics and the
paper starter results) and writes a single self-contained HTML page,
app/index.html, that opens in any browser without a server.

Standard library only, so it runs wherever the pipeline runs:

    python3 app/build_dashboard.py            # writes app/index.html
    python3 app/build_dashboard.py --json     # also writes app/dashboard_data.json

Re-run after ./run_phase0.sh or any estimation script so the page reflects the
current artefacts. Nothing in data/ is modified.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
PROCESSED = ROOT / "data" / "processed"
DIAG = PROCESSED / "diagnostics"
RAW = ROOT / "data" / "raw"

# Human names for panel columns (fallback: the code itself).
SERIES_LABELS = {
    "AGG": "Aggregate / hardcore", "ALU": "Aluminium", "BRICK": "Bricks",
    "CEM": "Cement", "CLAY": "Clay", "DIESEL": "Diesel", "IRON": "Iron",
    "IRONSTEEL": "Iron and steel", "LABOUR": "Labour", "LIME": "Lime",
    "MURRAM": "Murram", "NAILS": "Nails and fasteners", "PAINT": "Paints",
    "PIPES": "Pipes", "SAND": "Sand", "STEEL": "Steel", "TILES": "Tiles",
    "TIMBER": "Timber",
    "CIPI_ALL": "CIPI headline", "CIPI_MAT": "CIPI materials",
    "CIPI_BLDG": "CIPI buildings", "CIPI_CIVIL": "CIPI civil works",
    "exchange_rate": "UGX per USD", "central_bank_rate": "Central bank rate (%)",
    "lending_rate": "Lending rate (%)", "cpi": "Consumer price index",
    "activity_indicator": "Composite activity indicator",
    "private_credit": "Private-sector credit growth (%)",
    "ppi_manufacturing": "PPI manufacturing",
}
MACRO_COLS = ["exchange_rate", "central_bank_rate", "lending_rate", "cpi",
              "activity_indicator", "private_credit", "ppi_manufacturing"]
AGGREGATE_COLS = ["CIPI_ALL", "CIPI_MAT", "CIPI_BLDG", "CIPI_CIVIL"]


# ----------------------------------------------------------------- helpers --
def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def num(x, nd: int | None = None):
    """Parse a numeric cell; blanks become None."""
    if x is None or str(x).strip() == "" or str(x).strip().lower() == "nan":
        return None
    try:
        v = float(x)
    except ValueError:
        return None
    return round(v, nd) if nd is not None else v


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def count_files(path: Path, exts: tuple[str, ...] = ()) -> int:
    if not path.exists():
        return 0
    return sum(1 for p in path.iterdir()
               if p.is_file() and (not exts or p.suffix.lower() in exts))


# --------------------------------------------------------------- sections --
def load_panel() -> dict:
    rows = read_csv(PROCESSED / "panel_v1.0.csv")
    if not rows:
        sys.exit("panel_v1.0.csv not found — run ./run_phase0.sh first")
    cols = [c for c in rows[0].keys() if c != "date"]
    dates = [r["date"][:7] for r in rows]
    series = {c: [num(r[c], 3) for r in rows] for c in cols}
    materials = [c for c in cols if c.isupper() and c not in AGGREGATE_COLS]
    aggregates = [c for c in AGGREGATE_COLS if c in cols]
    macro = [c for c in MACRO_COLS if c in cols]
    return {
        "dates": dates,
        "series": series,
        "groups": {"materials": materials, "aggregates": aggregates, "macro": macro},
        "labels": {c: SERIES_LABELS.get(c, c) for c in cols},
    }


def load_coverage() -> list[dict]:
    out = []
    for r in read_csv(PROCESSED / "coverage_report.csv"):
        code = r.get("") or r.get("series") or r.get("index")
        out.append({
            "code": code, "label": SERIES_LABELS.get(code, code),
            "first": r["first_obs"][:7], "last": r["last_obs"][:7],
            "n_obs": int(float(r["n_obs"])), "pct_missing": num(r["pct_missing"], 1),
        })
    return out


def load_splices() -> dict:
    rows = read_csv(PROCESSED / "splice_log.csv")
    factors = [num(r["splice_factor"]) for r in rows]
    factors = [f for f in factors if f is not None]
    no_overlap = [r for r in rows if "no-overlap" in (r.get("note") or "").lower()
                  or "no_overlap" in (r.get("note") or "").lower()
                  or r.get("splice_factor", "") == ""]
    by_series: dict[str, int] = {}
    for r in rows:
        by_series[r["series_code"]] = by_series.get(r["series_code"], 0) + 1
    vintages = sorted({r["older"] for r in rows} | {r["newer"] for r in rows})
    summary = [{
        "code": r["series_code"], "label": SERIES_LABELS.get(r["series_code"], r["series_code"]),
        "n_links": int(float(r["n_links"])), "n_no_overlap": int(float(r["n_no_overlap"])),
        "min_factor": num(r["min_splice_factor"], 4), "max_factor": num(r["max_splice_factor"], 4),
        "median_overlap": num(r["median_overlap"], 1),
    } for r in read_csv(DIAG / "rebasing_history_summary.csv")]
    return {
        "n_links": len(rows), "n_series": len(by_series), "n_vintages": len(vintages),
        "n_no_overlap": len(no_overlap),
        "min_factor": round(min(factors), 4) if factors else None,
        "max_factor": round(max(factors), 4) if factors else None,
        "n_unit": sum(1 for f in factors if abs(f - 1) < 1e-9),
        "summary": summary,
        "sample": [{"code": r["series_code"], "older": r["older"], "newer": r["newer"],
                    "factor": num(r["splice_factor"], 4), "note": r.get("note", "")}
                   for r in rows[:400]],
    }


def load_reconciliation() -> list[dict]:
    return [{
        "comparison": r["comparison"], "status": r["status"],
        "n_overlap": int(float(r["n_overlap"])), "start": r["start"][:7], "end": r["end"][:7],
        "corr": num(r["corr"], 3), "mad": num(r["mad_index_points"], 2),
        "rmse": num(r["rmse_index_points"], 2),
    } for r in read_csv(PROCESSED / "reconciliation_report.csv")]


def load_breaks() -> list[dict]:
    out = []
    for r in read_csv(DIAG / "bai_perron_style_breaks.csv"):
        dates = [d[:7] for d in (r.get("break_dates") or "").split(";") if d.strip()]
        out.append({"code": r["series"], "label": SERIES_LABELS.get(r["series"], r["series"]),
                    "n": int(float(r["n"])), "n_breaks": int(float(r["selected_breaks"] or 0)),
                    "dates": dates})
    return out


def load_stationarity() -> dict:
    rows = read_csv(DIAG / "unit_root_stationarity_tests.csv")
    tests = [{
        "code": r["series"], "label": SERIES_LABELS.get(r["series"], r["series"]),
        "n": int(float(r["n"])),
        "adf_p_level": num(r["adf_p_level"], 3), "kpss_p_level": num(r["kpss_p_level"], 3),
        "adf_p_diff": num(r["adf_p_diff"], 4), "kpss_p_diff": num(r["kpss_p_diff"], 3),
        "verdict": r["stationarity_hint"],
    } for r in rows]
    counts: dict[str, int] = {}
    for t in tests:
        counts[t["verdict"]] = counts.get(t["verdict"], 0) + 1
    return {"tests": tests, "counts": counts}


def load_fiscal() -> dict:
    rows = read_csv(PROCESSED / "government_funding_panel.csv")
    if not rows:
        return {}
    cols = [c for c in rows[0].keys() if c != "date"]
    return {"dates": [r["date"][:7] for r in rows],
            "series": {c: [num(r[c], 1) for r in rows] for c in cols}}


def load_papers(panel: dict) -> dict:
    # P3 — clusters
    p3 = [{"code": r["material"], "label": SERIES_LABELS.get(r["material"], r["material"]),
           "cluster": int(float(r["cluster"]))} for r in read_csv(ROOT / "p3_clusters.csv")]

    # P4 — spillover table + SIMI ranking
    sp_rows = read_csv(ROOT / "p4_spillover_table.csv")
    sp_names = [k for k in (sp_rows[0].keys() if sp_rows else []) if k != ""]
    spill = {"names": sp_names,
             "matrix": [[num(r[c], 2) for c in sp_names] for r in sp_rows]}
    simi = [{"code": r[""], "label": SERIES_LABELS.get(r[""], r[""]),
             "to_others": num(r["to_others"], 1), "from_others": num(r["from_others"], 1),
             "net": num(r["net"], 1), "simi": num(r["SIMI"], 0)}
            for r in read_csv(ROOT / "p4_simi_ranking.csv")]
    simi.sort(key=lambda d: -(d["simi"] or 0))

    # P6 — IRF / FEVD / sensitivity
    irf_rows = read_csv(ROOT / "p6_irf.csv")
    irf_cols = list(irf_rows[0].keys()) if irf_rows else []
    irf = {"shocks": irf_cols, "labels": {c: SERIES_LABELS.get(c, c) for c in irf_cols},
           "response": {c: [num(r[c], 3) for r in irf_rows] for c in irf_cols}}
    fevd_rows = read_csv(ROOT / "p6_fevd.csv")
    fevd_cols = list(fevd_rows[0].keys()) if fevd_rows else []
    fevd = {"sources": fevd_cols, "labels": {c: SERIES_LABELS.get(c, c) for c in fevd_cols},
            "share": {c: [num(r[c], 4) for r in fevd_rows] for c in fevd_cols}}
    sens = read_json(ROOT / "p6_sensitivity_vector.json", {})

    # P8 — DAM back-test
    p8 = [{"project": r["project"], "start": r["window_start"][:7], "end": r["window_end"][:7],
           "fixed_margin": num(r["fixed_final_margin"], 4), "dam_margin": num(r["dam_final_margin"], 4),
           "protected": num(r["margin_protected"], 4), "fixed_var": num(r["fixed_margin_var"], 6),
           "dam_var": num(r["dam_margin_var"], 6), "n_adjustments": int(float(r["n_adjustments"]))}
          for r in read_csv(ROOT / "p8_backtest_results.csv")]
    # Reference-project baskets straight from the simulator source (kept in sync by regex).
    baskets = {}
    src = ROOT / "src" / "estimation" / "p8_dam_simulator.py"
    if src.exists():
        m = re.search(r"REFERENCE_PROJECTS\s*=\s*\{(.*?)\n\}", src.read_text(), re.S)
        if m:
            for pm in re.finditer(r'"(\w+)":\s*\{([^}]*)\}', m.group(1)):
                baskets[pm.group(1)] = {k: float(v) for k, v in
                                        re.findall(r'"(\w+)":\s*(\.?[\d.]+)', pm.group(2))}
    # DAM margin path replay for the chart (mirror of simulate(), cost basket only)
    dam_paths = {}
    for row in p8:
        w = baskets.get(row["project"], {})
        mats = [m for m in w if m in panel["series"]]
        if not mats:
            continue
        tot = sum(w[m] for m in mats)
        idx = [i for i, d in enumerate(panel["dates"]) if row["start"] <= d <= row["end"]]
        cost = []
        for i in idx:
            vals = [(panel["series"][m][i], w[m] / tot) for m in mats]
            cost.append(sum(v * ww for v, ww in vals if v is not None))
        if cost and cost[0]:
            c0 = cost[0]
            dam_paths[row["project"]] = {
                "dates": [panel["dates"][i] for i in idx],
                "fixed_margin": [round(1 - c / c0, 4) for c in cost],
                "cost_index": [round(c / c0 * 100, 2) for c in cost],
                "basket": {m: round(w[m] / tot, 3) for m in mats},
                "basket_missing": [m for m in w if m not in panel["series"]],
            }

    # P9 — forecast metrics
    p9 = {}
    for r in read_csv(ROOT / "p9_forecast_metrics.csv"):
        p9[r["model"]] = {k: num(v, 4) for k, v in r.items() if k != "model"}

    return {"p3": p3, "p4": {"spillover": spill, "simi": simi}, "p6": {"irf": irf, "fevd": fevd, "sensitivity": sens},
            "p8": {"results": p8, "baskets": baskets, "paths": dam_paths}, "p9": p9}


def load_sources() -> dict:
    manifest = read_csv(RAW / "ubos_cipi_manifest.csv")
    ubos_dir = RAW / "ubos_cipi_downloads"
    datasources = read_csv(RAW / "mofped_bulk" / "catalog" / "datasources.csv")
    datasets = read_csv(RAW / "mofped_bulk" / "catalog" / "datasets.csv")
    series_cat = RAW / "mofped_bulk" / "catalog" / "series.csv"
    n_series_cat = 0
    if series_cat.exists():
        with open(series_cat, encoding="utf-8", newline="") as fh:
            n_series_cat = max(0, sum(1 for _ in fh) - 1)
    return {
        "ubos_release_files": count_files(ubos_dir, (".pdf", ".xlsx", ".xls")),
        "ubos_pdf": count_files(ubos_dir, (".pdf",)),
        "ubos_xlsx": count_files(ubos_dir, (".xlsx", ".xls")),
        "ubos_manifest_ok": sum(1 for r in manifest if r.get("status") == "ok"),
        "mofped_datasets_downloaded": count_files(RAW / "mofped_bulk" / "datasets", (".csv",)),
        "mofped_catalog_datasets": len(datasets),
        "mofped_catalog_series": n_series_cat,
        "mofped_sources": [{"name": r["Source"], "url": r["Source_Url"], "n": int(float(r["NDatasets"]))}
                           for r in datasources],
        "cipi_parser_inputs": count_files(RAW, (".xlsx", ".xls")),
    }


def load_codebase() -> dict:
    src = ROOT / "src"
    scripts = sorted(str(p.relative_to(ROOT)) for p in src.rglob("*") if p.suffix in (".py", ".R"))
    tests = ROOT / "tests" / "test_pipeline.py"
    n_tests = len(re.findall(r"^def test_", tests.read_text(), re.M)) if tests.exists() else 0
    return {"scripts": scripts, "n_scripts": len(scripts), "n_tests": n_tests,
            "stages": {
                "ingest": [s for s in scripts if "/ingest/" in s],
                "index": [s for s in scripts if "/index/" in s],
                "estimation": [s for s in scripts if "/estimation/" in s]}}


# ------------------------------------------------------ forecast parameters --
# The Workbench forecasts in the browser from a small, transparent parameter
# set per series, estimated here from panel_v1.0. Everything is ordinary
# statistics on monthly log-returns so a reviewer can reproduce it by hand.
import math

HALF_LIFE_MONTHS = 24      # weight recent behaviour more: w = 0.5 ** (age / half-life)
SHOCK_WINDOW = ("2022-03", "2023-03")   # the 2022 commodity shock, replayed as a scenario
FX_LAGS = 3                # pass-through measured over the current month + 3 lags


def _solve(a: list[list[float]], b: list[float]) -> list[float] | None:
    """Gaussian elimination with partial pivoting for the small OLS normal equations."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[p][c]) < 1e-12:
            return None
        m[c], m[p] = m[p], m[c]
        for r in range(n):
            if r != c:
                f = m[r][c] / m[c][c]
                for k in range(c, n + 1):
                    m[r][k] -= f * m[c][k]
    return [m[i][n] / m[i][i] for i in range(n)]


def _ols(y: list[float], x_rows: list[list[float]]) -> list[float] | None:
    k = len(x_rows[0])
    xtx = [[sum(r[i] * r[j] for r in x_rows) for j in range(k)] for i in range(k)]
    xty = [sum(r[i] * yy for r, yy in zip(x_rows, y)) for i in range(k)]
    return _solve(xtx, xty)


def estimate_series(dates: list[str], values: list, fx_returns: list | None) -> dict | None:
    """Trend, seasonality, volatility, persistence and FX pass-through for one series."""
    logs = [math.log(v) if (v is not None and v > 0) else None for v in values]
    rets = []  # (index, log return) for consecutive observed months
    for i in range(1, len(logs)):
        if logs[i] is not None and logs[i - 1] is not None:
            rets.append((i, logs[i] - logs[i - 1]))
    if len(rets) < 24:
        return None
    last_i = max(i for i, v in enumerate(values) if v is not None)
    n = len(rets)
    # exponentially weighted drift and volatility
    w = [0.5 ** ((last_i - i) / HALF_LIFE_MONTHS) for i, _ in rets]
    sw = sum(w)
    mu = sum(wi * r for wi, (_, r) in zip(w, rets)) / sw
    var = sum(wi * (r - mu) ** 2 for wi, (_, r) in zip(w, rets)) / sw
    sigma = math.sqrt(var)
    mu_full = sum(r for _, r in rets) / n
    sigma_full = math.sqrt(sum((r - mu_full) ** 2 for _, r in rets) / max(1, n - 1))
    # lag-1 autocorrelation of returns (persistence of shocks)
    pairs = [(rets[k - 1][1], rets[k][1]) for k in range(1, n) if rets[k][0] - rets[k - 1][0] == 1]
    if len(pairs) > 12:
        ma = sum(a for a, _ in pairs) / len(pairs); mb = sum(b for _, b in pairs) / len(pairs)
        cov = sum((a - ma) * (b - mb) for a, b in pairs)
        va = math.sqrt(sum((a - ma) ** 2 for a, _ in pairs) * sum((b - mb) ** 2 for _, b in pairs))
        phi = cov / va if va > 0 else 0.0
    else:
        phi = 0.0
    phi = max(-0.5, min(0.8, phi))
    # calendar-month seasonal factors on returns (demeaned), only with 5+ years
    seasonal = [0.0] * 12
    if n >= 60:
        by_m: dict[int, list[float]] = {}
        for i, r in rets:
            by_m.setdefault(int(dates[i][5:7]) - 1, []).append(r)
        raw = [sum(by_m.get(m, [0])) / max(1, len(by_m.get(m, []))) for m in range(12)]
        mean_raw = sum(raw) / 12
        seasonal = [round(x - mean_raw, 5) for x in raw]
    # exchange-rate pass-through: cumulative beta over current + FX_LAGS lags
    fx_beta = None
    if fx_returns:
        rows, ys = [], []
        for i, r in rets:
            lags = [fx_returns[i - k] if i - k >= 0 else None for k in range(FX_LAGS + 1)]
            if all(l is not None for l in lags):
                rows.append([1.0] + lags); ys.append(r)
        if len(rows) > 30:
            b = _ols(ys, rows)
            if b:
                fx_beta = round(max(0.0, min(1.5, sum(b[1:]))), 3)
    # the 2022 shock as a replayable path of monthly log-returns
    shock = []
    for i, r in rets:
        if SHOCK_WINDOW[0] < dates[i] <= SHOCK_WINDOW[1]:
            shock.append(round(r, 5))
    return {
        "last": values[last_i], "last_date": dates[last_i], "n_returns": n,
        "mu": round(mu, 5), "sigma": round(sigma, 5),
        "mu_full": round(mu_full, 5), "sigma_full": round(sigma_full, 5),
        "phi": round(phi, 3), "seasonal": seasonal, "fx_beta": fx_beta,
        "shock_2022": shock,
        "change_12m": (round(values[last_i] / values[last_i - 12] - 1, 4)
                       if last_i >= 12 and values[last_i - 12] else None),
    }


def load_forecast(panel: dict) -> dict:
    dates, series = panel["dates"], panel["series"]
    fx = series.get("exchange_rate")
    fx_ret = None
    if fx:
        fx_ret = [None] + [
            (math.log(fx[i]) - math.log(fx[i - 1])) if (fx[i] and fx[i - 1]) else None
            for i in range(1, len(fx))]
    out = {}
    for code in panel["groups"]["materials"] + panel["groups"]["aggregates"] + ["exchange_rate", "cpi"]:
        if code in series:
            est = estimate_series(dates, series[code], fx_ret if code not in ("exchange_rate",) else None)
            if est:
                out[code] = est
    macro_latest = {}
    for code in panel["groups"]["macro"]:
        vals = series[code]
        idx = [i for i, v in enumerate(vals) if v is not None]
        if idx:
            i = idx[-1]
            macro_latest[code] = {"value": vals[i], "date": dates[i],
                                  "change_12m": (round(vals[i] / vals[i - 12] - 1, 4) if i >= 12 and vals[i - 12] else None),
                                  "delta_12m": (round(vals[i] - vals[i - 12], 2) if i >= 12 and vals[i - 12] is not None else None)}
    # average pairwise correlation of material returns -> common-factor loading for joint simulation
    mats = [c for c in panel["groups"]["materials"] if c in out and out[c]["n_returns"] >= 60]
    rets = {}
    for c in mats:
        v = series[c]
        rets[c] = [(math.log(v[i]) - math.log(v[i - 1])) if (v[i] and v[i - 1]) else None for i in range(1, len(v))]
    cors = []
    for a in range(len(mats)):
        for b in range(a + 1, len(mats)):
            pa, pb = rets[mats[a]], rets[mats[b]]
            xs = [(x, y) for x, y in zip(pa, pb) if x is not None and y is not None]
            if len(xs) < 30:
                continue
            mx = sum(x for x, _ in xs) / len(xs); my = sum(y for _, y in xs) / len(xs)
            sxy = sum((x - mx) * (y - my) for x, y in xs)
            sxx = sum((x - mx) ** 2 for x, _ in xs); syy = sum((y - my) ** 2 for _, y in xs)
            if sxx > 0 and syy > 0:
                cors.append(sxy / math.sqrt(sxx * syy))
    avg_corr = sum(cors) / len(cors) if cors else 0.0
    return {"series": out, "macro_latest": macro_latest,
            "common_corr": round(max(0.0, avg_corr), 4), "n_pairs": len(cors),
            "method": {"half_life_months": HALF_LIFE_MONTHS, "shock_window": SHOCK_WINDOW, "fx_lags": FX_LAGS}}


def build_payload() -> dict:
    panel = load_panel()
    manifest = read_json(PROCESSED / "panel_manifest.json", {})
    return {
        "forecast": load_forecast(panel),
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "manifest": manifest,
        "panel": panel,
        "coverage": load_coverage(),
        "splices": load_splices(),
        "reconciliation": load_reconciliation(),
        "breaks": load_breaks(),
        "stationarity": load_stationarity(),
        "fiscal": load_fiscal(),
        "papers": load_papers(panel),
        "sources": load_sources(),
        "code": load_codebase(),
    }


PAGES = {  # template -> output, both under app/
    "template.html": "index.html",
    "workbench_template.html": "workbench.html",
}


def render(payload: dict, template_name: str) -> str:
    template = (APP / template_name).read_text(encoding="utf-8")
    vendor = APP / "vendor" / "echarts.min.js"
    if vendor.exists():
        lib = "<script>" + vendor.read_text(encoding="utf-8") + "</script>"
    else:  # fall back to the CDN copy if the vendored file is absent
        lib = ('<script src="https://cdnjs.cloudflare.com/ajax/libs/echarts/5.4.3/'
               'echarts.min.js"></script>')
    fonts = APP / "vendor" / "lato.css"
    if fonts.exists():  # Lato embedded as base64 @font-face so the pages need no font host
        font_tag = "<style>" + fonts.read_text(encoding="utf-8") + "</style>"
    else:
        font_tag = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
                    'family=Lato:wght@400;700;900&display=swap">')
    data = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    return (template.replace("<!--__ECHARTS__-->", lib)
                    .replace("<!--__FONTS__-->", font_tag)
                    .replace("/*__CIO_DATA__*/null", data))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="also write app/dashboard_data.json")
    args = ap.parse_args()

    payload = build_payload()
    if args.json:
        (APP / "dashboard_data.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")
    m = payload["manifest"]
    for template_name, out_name in PAGES.items():
        if not (APP / template_name).exists():
            continue
        html = render(payload, template_name)
        (APP / out_name).write_text(html, encoding="utf-8")
        print(f"wrote app/{out_name} ({len(html)/1e6:.2f} MB)")
    print(f"panel v{m.get('panel_version')} — {m.get('n_months')} months × {m.get('n_series')} series; "
          f"forecast parameters for {len(payload['forecast']['series'])} series")


if __name__ == "__main__":
    main()
