#!/usr/bin/env python3
"""
cycle.py — the automated operating cycle (run from cron; see deploy/crontab.example).

    python src/market/cycle.py daily    # harvest UBOS + KNBS; on a new release: settle, refit, open
    python src/market/cycle.py weekly   # refresh weekly drivers + rainfall, write the weekly note

Both are idempotent: running twice does nothing new. Every step is logged to
data/market/cycle_log.csv; a failing step is logged and the rest still run.
"""
from __future__ import annotations

import argparse
import csv
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / "data" / "market" / "cycle_log.csv"
PY = sys.executable


def _contract_countries() -> list[str]:
    sys.path.insert(0, str(ROOT / "src" / "market"))
    from country import load_country, list_countries
    return [c for c in list_countries() if load_country(c)["markets"]]


COUNTRIES = _contract_countries()               # countries with settled contracts


def log(step: str, status: str, detail: str = "") -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    new = not LOG.exists()
    with open(LOG, "a", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["utc", "step", "status", "detail"])
        w.writerow([datetime.now(timezone.utc).isoformat(timespec="seconds"), step, status, detail[:500]])
    print(f"[{status}] {step} {detail[:200]}")


def run(step: str, *args: str, db: str | None = None) -> str:
    cmd = [PY, "-W", "ignore", *args] + (["--db", db] if db else [])
    try:
        out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=3600, check=True).stdout
        log(step, "ok", out.strip().splitlines()[-1] if out.strip() else "")
        return out
    except subprocess.CalledProcessError as err:
        log(step, "failed", (err.stderr or err.stdout or "").strip().splitlines()[-1:][0] if (err.stderr or err.stdout) else "")
    except Exception:
        log(step, "failed", traceback.format_exc().splitlines()[-1])
    return ""


def latest_release_month(country: str) -> str:
    sys.path.insert(0, str(ROOT / "src" / "market"))
    from country import load_country
    from settlement import load_releases
    return str(load_releases(load_country(country)).release_month.max().date())


def daily(db: str | None) -> None:
    before = {c: latest_release_month(c) for c in COUNTRIES}
    run("harvest UBOS", "src/ingest/pull_ubos_cipi.py", "--out", "data/raw/ubos_cipi_downloads")
    run("harvest KNBS", "src/ingest/pull_knbs_cipi.py")
    run("harvest Stats SA", "src/ingest/statssa_p01511.py", "pull")
    for c in COUNTRIES:
        after = latest_release_month(c)
        mkt = ["src/market/run_market.py"]
        run(f"settle {c}", *mkt, *(["--db", db] if db else []), "settle", "--country", c)
        if after != before[c]:
            log(f"new release {c}", "ok", f"{before[c]} -> {after}")
            if c == "uganda":
                run("forecast backtest", "src/forecast/run_forecast.py", "backtest")
                run("forecast", "src/forecast/run_forecast.py", "forecast")
        run(f"open {c}", *mkt, *(["--db", db] if db else []), "open", "--country", c)


def weekly(db: str | None) -> None:
    run("rainfall", "src/ingest/build_rainfall_block.py")
    run("fx history", "src/ingest/build_fx_history.py")
    run("weekly notes", "src/forecast/weekly_note.py", "--country", "all", db=db)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("job", choices=["daily", "weekly"])
    ap.add_argument("--db", help="ledger path (default data/market/exchange.sqlite)")
    a = ap.parse_args()
    (daily if a.job == "daily" else weekly)(a.db)
