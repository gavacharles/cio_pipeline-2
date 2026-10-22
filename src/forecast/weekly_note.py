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

Outputs data/processed/notes/weekly_<date>.md and .html (the participant app shows the latest).

    python src/forecast/weekly_note.py [--no-fetch] [--db data/market/exchange.sqlite]
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


def drivers_section(weekly: pd.DataFrame) -> list[str]:
    rows = [("Brent crude (USD/bbl)", "brent_usd"), ("UGX per USD", "ugx_per_usd"),
            ("KES per USD", "kes_per_usd"), ("RWF per USD", "rwf_per_usd")]
    out = ["| Driver | Latest | 1 week | 4 weeks | 13 weeks |", "|---|---|---|---|---|"]
    for name, c in rows:
        s = weekly[c]
        out.append(f"| {name} | {_fmt(s.dropna().iloc[-1])} | {_fmt(_chg(s, 7), pct=True)} | "
                   f"{_fmt(_chg(s, 28), pct=True)} | {_fmt(_chg(s, 91), pct=True)} |")
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


def crowd_section(db_path: Path) -> list[str]:
    if not db_path.exists():
        return ["_No price reports yet. Participants report the prices they pay in the app each week._"]
    from reports import Participants
    from country import load_country
    db, out = Participants(db_path), []
    for c in ("uganda", "kenya", "rwanda"):
        cfg = load_country(c)
        s = db.crowd_summary(c, cfg.get("price_items", []))
        s = s[s.reports > 0]
        if s.empty:
            continue
        out += [f"**{cfg['country']}** ({cfg['currency']})", "",
                "| Item | Median price | Reporters | Change vs 4 weeks |", "|---|---|---|---|"]
        out += [f"| {r['name']} | {_fmt(r['median'], 0)} per {r['unit']} | {r['reporters']} | "
                f"{_fmt(r['change_pct'], pct=True)} |" for _, r in s.iterrows()]
        out.append("")
    return out or ["_No price reports in the last 12 weeks._"]


def market_section(db_path: Path) -> list[str]:
    if not db_path.exists():
        return ["_No open contracts._"]
    from ledger import Exchange
    from nowcast import expected_change
    ms = Exchange(db_path).markets(status="open")
    if not ms:
        return ["_No open contracts._"]
    out = ["| Contract | Period | Crowd expects | Model expected | Closes |", "|---|---|---|---|---|"]
    for mk in ms:
        out.append(f"| {mk['country'].title()}: {mk['title']} | {mk['ref_month']} | "
                   f"{expected_change(np.array(mk['prices']), mk['cuts']):+.2f}% | "
                   f"{expected_change(np.array(mk['prior']), mk['cuts']):+.2f}% | {mk['closes'][:10]} |")
    return out


def build(fetch: bool = True, db_path: Path = DEFAULT_DB) -> Path:
    if fetch:
        import build_weekly_drivers
        build_weekly_drivers.build()
    cfg = yaml.safe_load(open(ROOT / "config" / "forecast_model.yaml", encoding="utf-8"))
    structure = read_release(latest_weighted_release([ROOT / "data" / "raw", ROOT / "data" / "raw" / "ubos_cipi_downloads"]))
    macro = load_macro(cfg, ROOT)
    ext_f = ROOT / "data" / "processed" / "macro_extension_monthly.csv"
    ext = pd.read_csv(ext_f, parse_dates=["date"]).set_index("date") if ext_f.exists() else None
    weekly = pd.read_csv(ROOT / "data" / "raw" / "weekly_drivers.csv", parse_dates=["date"]).set_index("date")
    fc, origin, n_known = forecast_section(cfg, structure, macro, ext, load_policy_events(cfg, ROOT))

    today = date.today()
    lines = [f"# Construction cost note — week of {today:%d %B %Y}", "",
             "_CiO Lab · Uganda, Kenya, Rwanda · play-money pilot; not investment advice._", "",
             "## This week's drivers", ""] + drivers_section(weekly) + ["",
             "## Uganda: expected change in input prices", "",
             f"Change from the last UBOS release (**{origin:%B %Y}**), with the {n_known} months of Brent and "
             "shilling readings since then built in. Apply these to your own last known quote for the "
             "same item. Range = 80% band.", "",
             "| Series | Month | Expected | Range | Without new data |", "|---|---|---|---|---|"]
    lines += [f"| {r.series} | {r.month} | {r['median']:+.1f}% | {r.lo:+.1f}% to {r.hi:+.1f}% | "
              f"{r.without_new_data:+.1f}% |" for _, r in fc.iterrows()]
    lines += ["", "July 2026 excise changes (fuel +Shs200/l, cement, paint) are included at 50% pass-through.",
              "", "## Prices reported by participants", ""] + crowd_section(db_path)
    lines += ["", "## Open forecasting contracts", ""] + market_section(db_path)
    lines += ["", "## Method", "",
              "Model: CiO structural forecaster (docs/FORECAST_MODEL.md) — UBOS's published weights, "
              "component models driven by oil, shilling, iron ore, CPI, supply-chain pressure, rainfall and "
              "public spending; refitted at the latest release and conditioned on newer readings. "
              "Kenya (KNBS, quarterly) and Rwanda rely on the drivers and crowd prices until their models "
              "have enough history. Sources: UBOS, KNBS, EIA, currency-api, ERA5."]
    md = "\n".join(lines) + "\n"
    NOTES.mkdir(parents=True, exist_ok=True)
    stem = NOTES / f"weekly_{today.isoformat()}"
    stem.with_suffix(".md").write_text(md, encoding="utf-8")
    stem.with_suffix(".html").write_text(to_html(md, f"Construction cost note {today:%d %b %Y}"), encoding="utf-8")
    return stem.with_suffix(".md")


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


def latest_note(kind: str = "html") -> Path | None:
    notes = sorted(NOTES.glob(f"weekly_*.{kind}"))
    return notes[-1] if notes else None


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-fetch", action="store_true", help="use the drivers already on disk")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    a = ap.parse_args()
    print("wrote", build(fetch=not a.no_fetch, db_path=Path(a.db)))
