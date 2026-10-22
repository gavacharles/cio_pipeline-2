#!/usr/bin/env python3
"""
weekly_note.py — the weekly construction-cost note for contractors.

UBOS publishes monthly, 1-2 months late; KNBS quarterly. Contractors need a view
every week. Each note combines:
  1. this week's drivers (Brent, UGX/KES/RWF per USD) from build_weekly_drivers.py;
  2. the structural forecast refitted at the latest CIPI release but CONDITIONED on the
     Brent and UGX readings observed since then (model.known_primitives), so the weeks
     between releases are not wasted;
  3. crowd prices: weekly medians of participants' price reports (src/market/reports.py);
  4. market consensus: open contracts, crowd vs model (src/market/ledger.py).

One note per country: data/processed/notes/weekly_<country>_<date>.{md,html}
  - uganda: structural model (monthly, UBOS weights) conditioned on new Brent/UGX readings
  - kenya:  quarterly model for the KNBS overall/building/civil indices, conditioned on
            observed Brent and KES quarters; bands from walk-forward backtest errors
  - south_africa: latest Stats SA P0151.1 readings and next-month contract expectations
  - every other country: drivers, the latest official reading where one exists
            (config/official_readings.yaml), and an imported-input cost-pressure outlook
            (cost_pressure.py), plus crowd prices
The participant app shows the latest note for the participant's country.

    python src/forecast/weekly_note.py [--country uganda|kenya|rwanda|all] [--no-fetch] [--db ...]
"""
from __future__ import annotations

import argparse
import html
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "forecast"))
sys.path.insert(0, str(ROOT / "src" / "market"))
sys.path.insert(0, str(ROOT / "src" / "ingest"))

from index_structure import read_release, latest_weighted_release            # noqa: E402
from model import ForecastModel, load_macro, load_policy_events, known_primitives  # noqa: E402

NOTES = ROOT / "data" / "processed" / "notes"
DEFAULT_DB = ROOT / "data" / "market" / "exchange.sqlite"
KEY = {"ALL": "Overall construction inputs", "diesel": "Diesel", "cement": "Cement",
       "high tensile steel bars": "Rebar", "sand": "Sand", "labour": "Labour"}


def _chg(s: pd.Series, days: int) -> float | None:
    s = s.dropna()
    if s.empty:
        return None
    past = s[s.index <= s.index[-1] - pd.Timedelta(days=days)]
    return float(s.iloc[-1] / past.iloc[-1] - 1) * 100 if len(past) else None


def _fmt(x, nd=1, pct=False):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "–"
    return f"{x:+.{nd}f}%" if pct else f"{x:,.{nd}f}"


def ccy(country: str) -> tuple[str, str]:
    """(currency code, weekly-drivers column) from the country config."""
    from country import load_country
    cfg = load_country(country)
    return cfg["currency"], f"{cfg['fx_code']}_per_usd"


def drivers_section(weekly: pd.DataFrame, country: str) -> list[str]:
    ccy_code, col = ccy(country)
    if col not in weekly.columns or weekly[col].dropna().empty:
        return [f"_No exchange-rate readings for {ccy_code} yet; Brent in USD only._", "",
                f"Brent crude: {_fmt(weekly['brent_usd'].dropna().iloc[-1])} USD/bbl "
                f"({_fmt(_chg(weekly['brent_usd'], 91), pct=True)} over 13 weeks)."]
    ccy_ = ccy_code
    w = weekly.assign(oil_local=weekly["brent_usd"] * weekly[col])
    rows = [("Brent crude (USD/bbl)", "brent_usd"), (f"{ccy_} per USD", col), (f"Brent in {ccy_}", "oil_local")]
    out = ["| Driver | Latest | 1 week | 4 weeks | 13 weeks | 52 weeks |", "|---|---|---|---|---|---|"]
    for name, c in rows:
        s = w[c]
        out.append(f"| {name} | {_fmt(s.dropna().iloc[-1])} | {_fmt(_chg(s, 7), pct=True)} | "
                   f"{_fmt(_chg(s, 28), pct=True)} | {_fmt(_chg(s, 91), pct=True)} | {_fmt(_chg(s, 364), pct=True)} |")
    return out


def forecast_section(cfg, structure, macro, ext, events, months_ahead: int = 4):
    m = ForecastModel(cfg).fit(structure, macro)
    m.events = events
    today = pd.Timestamp(date.today()).to_period("M").to_timestamp()
    H = max(1, (today.to_period("M") - m.origin.to_period("M")).n + months_ahead)
    known = known_primitives(macro, ext, cfg, m.origin, H, m.prim_cols)
    P_known = m.simulate(H, n_paths=1000, known=known)
    P_blind = m.simulate(H, n_paths=1000)
    months = pd.date_range(m.origin + pd.DateOffset(months=1), periods=H, freq="MS")
    cols = list(structure.levels.columns)
    rows, focus = [], [today, today + pd.DateOffset(months=3)]
    for key, name in KEY.items():
        if key == "ALL":
            pk, pb, base = m.aggregate_paths(P_known, "ALL"), m.aggregate_paths(P_blind, "ALL"), \
                structure.published["ALL"].iloc[-1]
        else:
            j = cols.index(key)
            pk, pb, base = P_known[:, :, j], P_blind[:, :, j], structure.levels[key].iloc[-1]
        for d in focus:
            i = months.get_loc(d)
            q = np.percentile(pk[:, i] / base * 100 - 100, [10, 50, 90])
            blind = float(np.median(pb[:, i]) / base * 100 - 100)
            rows.append({"series": name, "month": d.strftime("%b %Y"), "median": q[1], "lo": q[0], "hi": q[2],
                         "without_new_data": blind})
    n_known = int((~np.isnan(known)).any(axis=1).sum())
    return pd.DataFrame(rows), m.origin, n_known


def crowd_section(db_path: Path, country: str) -> list[str]:
    if not db_path.exists():
        return ["_No price reports yet. Participants report the prices they pay in the app each week._"]
    from reports import Participants
    from country import load_country
    db, out = Participants(db_path), []
    for c in (country,):
        cfg = load_country(c)
        s = db.crowd_summary(c, cfg.get("price_items", []))
        s = s[s.reports > 0]
        if s.empty:
            continue
        out += [f"Prices in {cfg['currency']}.", "",
                "| Item | Median price | Reporters | Change vs 4 weeks |", "|---|---|---|---|"]
        out += [f"| {r['name']} | {_fmt(r['median'], 0)} per {r['unit']} | {r['reporters']} | "
                f"{_fmt(r['change_pct'], pct=True)} |" for _, r in s.iterrows()]
        out.append("")
    return out or ["_No price reports in the last 12 weeks._"]


def market_section(db_path: Path, country: str) -> list[str]:
    if not db_path.exists():
        return ["_No open contracts._"]
    from ledger import Exchange
    from nowcast import expected_change
    ms = Exchange(db_path).markets(status="open", country=country)
    if not ms:
        return ["_No open contracts._"]
    out = ["| Contract | Period | Crowd expects | Model expected | Closes |", "|---|---|---|---|---|"]
    for mk in ms:
        out.append(f"| {mk['title']} | {mk['ref_month']} | "
                   f"{expected_change(np.array(mk['prices']), mk['cuts']):+.2f}% | "
                   f"{expected_change(np.array(mk['prior']), mk['cuts']):+.2f}% | {mk['closes'][:10]} |")
    return out


HEADER = "_CiO Lab construction cost note · play-money pilot · not investment advice._"


def _write(country: str, md: str, today: date) -> Path:
    NOTES.mkdir(parents=True, exist_ok=True)
    stem = NOTES / f"weekly_{country}_{today.isoformat()}"
    stem.with_suffix(".md").write_text(md, encoding="utf-8")
    stem.with_suffix(".html").write_text(to_html(md, f"{country.title()} construction cost note {today:%d %b %Y}"),
                                         encoding="utf-8")
    return stem.with_suffix(".md")


def uganda_body(weekly) -> list[str]:
    cfg = yaml.safe_load(open(ROOT / "config" / "forecast_model.yaml", encoding="utf-8"))
    structure = read_release(latest_weighted_release([ROOT / "data" / "raw", ROOT / "data" / "raw" / "ubos_cipi_downloads"]))
    macro = load_macro(cfg, ROOT)
    ext_f = ROOT / "data" / "processed" / "macro_extension_monthly.csv"
    ext = pd.read_csv(ext_f, parse_dates=["date"]).set_index("date") if ext_f.exists() else None
    fc, origin, n_known = forecast_section(cfg, structure, macro, ext, load_policy_events(cfg, ROOT))
    lines = ["## Expected change in input prices", "",
             f"Change from the last UBOS release (**{origin:%B %Y}**), with the {n_known} months of Brent and "
             "shilling readings since then built in. Apply these to your own last known quote for the "
             "same item. Range = 80% band.", "",
             "| Series | Month | Expected | Range | Without new data |", "|---|---|---|---|---|"]
    lines += [f"| {r.series} | {r.month} | {r['median']:+.1f}% | {r.lo:+.1f}% to {r.hi:+.1f}% | "
              f"{r.without_new_data:+.1f}% |" for _, r in fc.iterrows()]
    lines += ["", "July 2026 excise changes (fuel +Shs200/l, cement, paint) are included at 50% pass-through."]
    return lines


def kenya_body(weekly) -> list[str]:
    from quarterly_model import QuarterlyModel, quarterly_drivers, backtest
    from country import load_country
    from settlement import load_releases, history
    cfg = load_country("kenya")
    rel = load_releases(cfg)
    D = quarterly_drivers("kes_per_usd")
    latest = rel.release_month.max()
    lines = ["## Latest KNBS readings", "",
             f"KNBS Construction Input Price Index, latest release **Q{latest.quarter} {latest.year}** "
             "(quarterly; base Dec 2019 = 100).", "",
             "| Series | Index | vs previous quarter | vs a year earlier |", "|---|---|---|---|"]
    for m in cfg["markets"]:
        lv = history(rel, m["label"], cfg).dropna()
        q1 = lv.iloc[-1] / lv.iloc[-2] - 1 if len(lv) > 1 else np.nan
        y1 = lv.iloc[-1] / lv.get(lv.index[-1] - pd.DateOffset(years=1), np.nan) - 1
        lines.append(f"| {m['title']} | {lv.iloc[-1]:.2f} | {_fmt(q1 * 100, pct=True)} | {_fmt(y1 * 100, pct=True)} |")
    lines += ["", "## Expected change in the next KNBS prints", "",
              "Quarterly model driven by the shilling and Brent in shillings, conditioned on the months already "
              "observed. Range = 80% band from the model's own past errors (walk-forward backtest). "
              "Only the three cost indices are forecast; for single materials the model did not beat a simple "
              "trend, so read their latest readings above with this week's drivers.", "",
              "| Index | Quarter | Expected vs latest print | Range | Driver months observed |", "|---|---|---|---|---|"]
    for code in ("KE_CIPI", "KE_BUILD", "KE_CIVIL"):
        m = next(x for x in cfg["markets"] if x["code"] == code)
        lv = history(rel, m["label"], cfg)
        mod = QuarterlyModel().fit(lv, D)
        paths, futq = mod.simulate(2, known=D[D.index > mod.origin])
        bt = backtest(lv, D)
        for h in (1, 2):
            sim = 100 * np.log(paths[:, h - 1] / mod.last_level)
            med = float(np.median(sim))
            g = bt[bt.h == h]
            half = float(np.quantile(np.abs(g.actual - g.model), 0.8)) if len(g) else np.nan
            months = int(D["months"].get(futq[h - 1], 0)) if futq[h - 1] in D.index else 0
            lines.append(f"| {m['title']} | Q{futq[h - 1].quarter} {futq[h - 1].year} | {med:+.1f}% | "
                         f"{med - half:+.1f}% to {med + half:+.1f}% | {months} of 3 |")
    return lines


def south_africa_body(weekly) -> list[str]:
    from country import load_country
    from settlement import load_releases, history, first_print
    from nowcast import mom_changes, predictive_probs, expected_change
    cfg = load_country("south_africa")
    rel = load_releases(cfg)
    latest = rel.release_month.max()
    nxt = latest + pd.DateOffset(months=1)
    lines = ["## Latest Stats SA readings", "",
             f"Stats SA P0151.1 construction materials price indices, latest release **{latest:%B %Y}** "
             "(monthly). Changes are computed inside each release, so rebasing does not distort them.", "",
             "| Series | Change on previous month | Change on a year earlier | Expected next month |",
             "|---|---|---|---|"]
    for m in cfg["markets"]:
        fp = first_print(rel, m["label"], latest)
        yr = rel[(rel.series_label == m["label"]) & (rel.release_month == latest)].set_index("date")["index_value"]
        y1 = (yr.iloc[-1] / yr.iloc[0] - 1) * 100 if len(yr) >= 3 else np.nan
        h = history(rel, m["label"], cfg)
        r = mom_changes(h)
        exp = expected_change(predictive_probs(r, nxt, m["cuts"], 1, 0.02), m["cuts"]) if len(r) > 24 else np.nan
        lines.append(f"| {m['title']} | {_fmt(fp['value'] if fp else None, 2, pct=True)} | "
                     f"{_fmt(y1, pct=True)} | {_fmt(exp, 2, pct=True)} |")
    lines += ["", f"Expected = the opening price of the {nxt:%B %Y} contract (recent change patterns; backtest over "
              "43 months beat plain frequencies for 7 of 12 contract-horizons, none significantly). A driver-based "
              "South Africa model is next."]
    return lines


def official_reading(country: str) -> list[str]:
    f = ROOT / "config" / "official_readings.yaml"
    r = (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get(country) if f.exists() else None
    if not r:
        return []
    parts = [f"level {r['level']}" if r.get("level") is not None else None,
             f"{r['change_period_pct']:+.1f}% on the previous period" if r.get("change_period_pct") is not None else None,
             f"{r['change_year_pct']:+.1f}% on a year earlier" if r.get("change_year_pct") is not None else None]
    q = "" if r.get("quality") == "official" else " (official figure as reported in the press; verify)"
    return [f"**Latest official reading:** {r['series']}, {r['period']}: "
            + ", ".join(x for x in parts if x) + f"{q}. Source: {r['source']}", ""]


def pressure_section(country: str) -> list[str]:
    from cost_pressure import pressure_history, forecast
    ccy_code, col = ccy(country)
    try:
        hist, fc = pressure_history(col), forecast(col)
    except Exception:
        return ["_Cost-pressure indicator unavailable (no exchange-rate history)._"]
    if hist.empty or not fc:
        return ["_Cost-pressure indicator unavailable (no exchange-rate history)._"]
    last3 = float(hist.tail(3).sum())
    lines = ["**Imported-input cost pressure** (oil in " + ccy_code + " and the exchange rate, weighted like the "
             "official baskets in the pilot countries; an indicator, not a price index):", "",
             "| Window | Pressure on input costs | 80% range |", "|---|---|---|",
             f"| Last 3 months (observed) | {last3:+.1f}% | – |"]
    for h, (med, lo, hi) in fc.items():
        lines.append(f"| Next {h} months | {med:+.1f}% | {lo:+.1f}% to {hi:+.1f}% |")
    lines += ["", "In Uganda and South Africa this indicator's 3-month changes correlate 0.26–0.37 with the official "
              "construction indices (0.45–0.58 with Uganda's diesel index): it captures the imported part of "
              "cost moves, not local materials or labour. Price reports from participants fill that gap."]
    return lines


def generic_body(weekly, country: str) -> list[str]:
    from country import load_country
    cfg = load_country(country)
    return (["## Official index", "", f"Status: {cfg['settlement']['publication']}.", ""]
            + official_reading(country) + ["## Cost pressure outlook", ""] + pressure_section(country))


BODIES = {"uganda": uganda_body, "kenya": kenya_body, "south_africa": south_africa_body}


def build(country: str = "uganda", fetch: bool = True, db_path: Path = DEFAULT_DB) -> Path:
    if fetch:
        import build_weekly_drivers
        build_weekly_drivers.build()
    from country import load_country
    cfg = load_country(country)
    weekly = pd.read_csv(ROOT / "data" / "raw" / "weekly_drivers.csv", parse_dates=["date"]).set_index("date")
    today = date.today()
    lines = [f"# {cfg['country']} construction cost note — week of {today:%d %B %Y}", "", HEADER, "",
             "## This week's drivers", ""] + drivers_section(weekly, country) + [""]
    lines += BODIES[country](weekly) if country in BODIES else generic_body(weekly, country)
    lines += ["", "## Prices reported by participants", ""] + crowd_section(db_path, country)
    lines += ["", "## Open forecasting contracts", ""] + market_section(db_path, country)
    lines += ["", "## Sources", "",
              "UBOS (Uganda CIPI), KNBS (Kenya CIPI), EIA (Brent), IMF and currency-api (exchange rates), "
              "ERA5 (rainfall); methods in docs/FORECAST_MODEL.md and docs/OPERATIONS.md."]
    return _write(country, "\n".join(lines) + "\n", today)


def to_html(md: str, title: str) -> str:
    """Small markdown subset (headings, tables, emphasis, paragraphs) -> standalone page."""
    out, table = [], []

    def inline(t):
        t = html.escape(t)
        import re
        t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
        return re.sub(r"_(.+?)_", r"<em>\1</em>", t)

    def flush():
        if table:
            head, body = table[0], table[2:]
            out.append("<div class=t><table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in head)
                       + "</tr></thead><tbody>" + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r)
                                                          + "</tr>" for r in body) + "</tbody></table></div>")
            table.clear()
    for line in md.splitlines():
        if line.startswith("|"):
            table.append([c.strip() for c in line.strip("|").split("|")])
            continue
        flush()
        if line.startswith("# "):
            out.append(f"<h1>{inline(line[2:])}</h1>")
        elif line.startswith("## "):
            out.append(f"<h2>{inline(line[3:])}</h2>")
        elif line.strip():
            out.append(f"<p>{inline(line)}</p>")
    flush()
    css = (":root{--bg:#fbfaf7;--fg:#1d1d1b;--mut:#6b6a66;--line:#e3e0d8;--acc:#b5651d}"
           "@media (prefers-color-scheme:dark){:root{--bg:#141412;--fg:#ecebe6;--mut:#a3a29c;--line:#33322e;--acc:#e0a060}}"
           "body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,sans-serif}"
           "main{max-width:820px;margin:0 auto;padding:24px 16px}h1{font-size:1.6rem;margin:.2em 0}"
           "h2{font-size:1.15rem;margin-top:1.8em;border-bottom:2px solid var(--acc);padding-bottom:4px}"
           "em{color:var(--mut)}.t{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:.92rem}"
           "th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);white-space:nowrap}"
           "th{color:var(--mut);font-weight:600}")
    return (f"<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport "
            f"content='width=device-width,initial-scale=1'><title>{html.escape(title)}</title>"
            f"<style>{css}</style></head><body><main>{''.join(out)}</main></body></html>")


def latest_note(country: str, kind: str = "html") -> Path | None:
    notes = sorted(NOTES.glob(f"weekly_{country}_*.{kind}"))
    return notes[-1] if notes else None


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    from country import list_countries
    ap.add_argument("--country", default="all", choices=["all", *list_countries()])
    ap.add_argument("--no-fetch", action="store_true", help="use the drivers already on disk")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    a = ap.parse_args()
    fetch = not a.no_fetch
    for c in (list_countries() if a.country == "all" else [a.country]):
        print("wrote", build(c, fetch=fetch, db_path=Path(a.db)))
        fetch = False                      # drivers fetched once per run
