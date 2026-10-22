#!/usr/bin/env python3
"""
seed_demo.py — fill a SEPARATE demo database so a walkthrough is not an empty screen.

Creates demo participants in Uganda, Kenya and Rwanda, opens the real contracts for the
next official prints (same code path as the daily cycle), places a spread of demo trades,
and adds six weeks of ILLUSTRATIVE price reports. The prices are invented round numbers
around plausible levels, not observations; run the app with CIO_DEMO=1 so every page says so.
Never point this at the live database.

    python src/webapp/seed_demo.py --db data/market/demo.sqlite
    CIO_DB=data/market/demo.sqlite CIO_DEMO=1 CIO_ADMIN_KEY=... uvicorn --app-dir src/webapp app:app
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "market"))

from country import load_country             # noqa: E402
from ledger import Exchange, ExchangeError   # noqa: E402
from reports import Participants             # noqa: E402

PEOPLE = {   # fictional, clearly labelled
    "uganda": [("Demo Contractor A", "Demo Builders Ltd"), ("Demo QS B", "Demo Cost Consultants"),
               ("Demo Developer C", "Demo Homes"), ("Demo Supplier D", "Demo Hardware")],
    "kenya": [("Demo Contractor E", "Demo Construction KE"), ("Demo QS F", "Demo QS Partners")],
    "rwanda": [("Demo Contractor G", "Demo Batiment RW")],
}
# Illustrative starting prices (local currency) — invented for the demo, not data.
ILLUSTRATIVE = {
    "uganda": {"cement_50kg": 35000, "rebar_y12": 45000, "rebar_y16": 80000, "iron_sheet": 38000, "diesel": 5500,
               "sand": 450000, "aggregate": 600000, "block_6in": 2500, "timber_2x4": 1500, "mason_day": 40000},
    "kenya": {"cement_50kg": 780, "rebar_y12": 1100, "iron_sheet": 900, "diesel": 180, "ballast": 2200,
              "sand": 2000, "block_6in": 65, "mason_day": 1500},
    "rwanda": {"cement_50kg": 13000, "rebar_y12": 15000, "iron_sheet": 12000, "diesel": 1900, "sand": 15000,
               "aggregate": 20000, "brick": 150, "mason_day": 6000},
}
TOWNS = {"uganda": ["Kampala", "Mukono", "Wakiso", "Jinja", "Mbarara"], "kenya": ["Nairobi", "Mombasa", "Nakuru"],
         "rwanda": ["Kigali", "Musanze"]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(ROOT / "data" / "market" / "demo.sqlite"))
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    db = Path(a.db)
    if db.name == "exchange.sqlite":
        sys.exit("refusing to seed the live database name; use a separate file such as demo.sqlite")
    rng = np.random.default_rng(a.seed)

    for c in ("uganda", "kenya"):         # real contracts, opened exactly as the daily cycle does
        subprocess.run([sys.executable, "-W", "ignore", str(ROOT / "src" / "market" / "run_market.py"),
                        "--db", str(db), "open", "--country", c], cwd=ROOT, check=False, capture_output=True)

    codes = []
    with Participants(db) as pp, Exchange(db, 1000) as ex:
        known = {p["name"] for p in pp.all()}
        for country, people in PEOPLE.items():
            items = load_country(country).get("price_items", [])
            for name, org in people:
                if name in known:
                    continue
                code = pp.invite(name, org, country)
                handle = pp.by_token(pp.redeem(code))["handle"]
                ex.open_account(handle)
                codes.append((country, name, code))
                for wk in range(6, -1, -1):          # six weeks of illustrative reports, drifting up
                    on = date.today() - timedelta(weeks=wk)
                    for it in rng.choice(items, size=min(4, len(items)), replace=False):
                        base = ILLUSTRATIVE[country].get(it["code"])
                        if base:
                            price = base * (1 + 0.004 * (6 - wk)) * rng.normal(1, 0.03)
                            pp.add_report(handle, country, it["code"], round(price, -1 if base < 1000 else -2),
                                          str(rng.choice(TOWNS[country])), "demo", on=on)
                for m in ex.markets(status="open", country=country):
                    if rng.random() < 0.6:
                        o = int(np.argmax(m["prices"]) + rng.integers(-1, 2))
                        o = min(max(o, 0), len(m["outcomes"]) - 1)
                        try:
                            ex.trade(handle, m["id"], o, float(rng.integers(5, 40)))
                        except ExchangeError:
                            pass
    print(f"demo database: {db}")
    for country, name, code in codes:
        print(f"  {country:<7} {name:<20} invite code {code}")
    print("Run the app with CIO_DB pointing here and CIO_DEMO=1.")


if __name__ == "__main__":
    main()
