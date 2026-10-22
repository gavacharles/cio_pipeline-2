"""
reports.py — participants and their weekly price reports (same sqlite file as the ledger).

Contractors price work from the quotes they get each week, not from a monthly index
published 1-2 months late. Participants therefore report what they actually paid or
were quoted (item, price, place). Weekly medians of those reports are the crowd price
series in the weekly note: faster than UBOS/KNBS and in shillings per bag, not index points.

    db = Participants("data/market/exchange.sqlite")
    code = db.invite("Jane Okello", "Okello Builders", "uganda")
    token = db.redeem(code)                 # sets the login token, opens a ledger account
    db.add_report(token, "cement_50kg", 34500, "Kampala - Nakawa", "hardware shop")
    db.crowd_summary("uganda", items)       # per item: latest-week median, change vs 4 weeks
"""
from __future__ import annotations

import secrets
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS participants (
    handle TEXT PRIMARY KEY, name TEXT NOT NULL, org TEXT, country TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'participant', invite_code TEXT UNIQUE NOT NULL,
    token TEXT UNIQUE, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS price_reports (
    id INTEGER PRIMARY KEY, ts TEXT NOT NULL, week TEXT NOT NULL, handle TEXT NOT NULL,
    country TEXT NOT NULL, item TEXT NOT NULL, price REAL NOT NULL, location TEXT NOT NULL,
    supplier TEXT, note TEXT);
CREATE INDEX IF NOT EXISTS price_reports_item ON price_reports (country, item, week);
"""


class ReportError(ValueError):
    pass


def week_of(d: date) -> str:
    """ISO week start (Monday) as YYYY-MM-DD."""
    return (d - timedelta(days=d.weekday())).isoformat()


class Participants:
    def __init__(self, path: str | Path = ":memory:"):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), timeout=10, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -------------------------------------------------------------- people --
    def invite(self, name: str, org: str, country: str, role: str = "participant") -> str:
        base = "".join(ch for ch in name.lower() if ch.isalnum())[:12] or "user"
        handle, k = base, 1
        while self.db.execute("SELECT 1 FROM participants WHERE handle=?", (handle,)).fetchone():
            k += 1
            handle = f"{base}{k}"
        code = secrets.token_hex(4).upper()
        with self.db:
            self.db.execute("INSERT INTO participants (handle, name, org, country, role, invite_code, created)"
                            " VALUES (?,?,?,?,?,?,?)", (handle, name, org, country, role, code,
                                                        datetime.now(timezone.utc).isoformat(timespec="seconds")))
        return code

    def redeem(self, code: str) -> str:
        row = self.db.execute("SELECT handle, token FROM participants WHERE invite_code=?",
                              (code.strip().upper(),)).fetchone()
        if row is None:
            raise ReportError("unknown invite code")
        token = secrets.token_urlsafe(24)
        with self.db:        # a code can be redeemed again (new device); the old token stops working
            self.db.execute("UPDATE participants SET token=? WHERE handle=?", (token, row["handle"]))
        return token

    def by_token(self, token: str | None) -> dict | None:
        if not token:
            return None
        row = self.db.execute("SELECT * FROM participants WHERE token=?", (token,)).fetchone()
        return dict(row) if row else None

    def all(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT handle, name, org, country, role, invite_code, "
                                                 "token IS NOT NULL AS active FROM participants ORDER BY created")]

    # ------------------------------------------------------------- reports --
    def add_report(self, handle: str, country: str, item: str, price: float, location: str,
                   supplier: str = "", note: str = "", items: list[str] | None = None,
                   on: date | None = None) -> int:
        if items is not None and item not in items:
            raise ReportError(f"unknown item {item!r}")
        if not price or price <= 0:
            raise ReportError("price must be a positive number")
        if not location.strip():
            raise ReportError("say where (town or area) the price applies")
        on = on or date.today()
        with self.db:
            cur = self.db.execute(
                "INSERT INTO price_reports (ts, week, handle, country, item, price, location, supplier, note)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (datetime.now(timezone.utc).isoformat(timespec="seconds"), week_of(on), handle, country, item,
                 float(price), location.strip(), supplier.strip(), note.strip()))
        return cur.lastrowid

    def reports(self, country: str, since_weeks: int = 12) -> pd.DataFrame:
        since = week_of(date.today() - timedelta(weeks=since_weeks))
        return pd.read_sql_query("SELECT * FROM price_reports WHERE country=? AND week>=? ORDER BY ts",
                                 self.db, params=(country, since))

    def crowd_summary(self, country: str, items: list[dict], weeks_back: int = 4) -> pd.DataFrame:
        """Per item: median of the latest week with reports, number of reports, distinct
        reporters, and the % change against the median `weeks_back` weeks earlier.
        Medians resist a single wrong or strategic report; one reporter per item-week
        counts once (their median) so nobody can move the series by reporting repeatedly."""
        df = self.reports(country, since_weeks=weeks_back + 8)
        rows = []
        for it in items:
            g = df[df["item"] == it["code"]]
            if g.empty:
                rows.append({"item": it["code"], "name": it["name"], "unit": it["unit"], "week": None,
                             "median": None, "reports": 0, "reporters": 0, "change_pct": None})
                continue
            per = g.groupby(["week", "handle"])["price"].median().groupby("week")
            med, n_rep = per.median(), per.size()
            last = med.index.max()
            prior_week = week_of(date.fromisoformat(last) - timedelta(weeks=weeks_back))
            prior = med[med.index <= prior_week]
            rows.append({"item": it["code"], "name": it["name"], "unit": it["unit"], "week": last,
                         "median": float(med[last]), "reports": int((g["week"] == last).sum()),
                         "reporters": int(n_rep[last]),
                         "change_pct": (float(med[last] / prior.iloc[-1] - 1) * 100) if len(prior) else None})
        return pd.DataFrame(rows)
