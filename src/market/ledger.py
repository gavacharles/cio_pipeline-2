"""
ledger.py — play-money exchange: accounts, markets, trades, settlement (sqlite).

Points have no cash value. The ledger is the tournament phase of the market:
it shows who forecasts construction costs well and how accurate the crowd's
consensus is, before anyone asks a regulator about real money.

Every trade stores the post-trade prices, so the price history of each
market is the consensus forecast over time (the data product).

    ex = Exchange("data/market/exchange.sqlite")
    ex.open_account("contractor_a")
    mid = ex.create_market(...)
    ex.trade("contractor_a", mid, outcome=3, shares=20)
    ex.settle(mid, value=0.42, source="06_2026CIPI_APRIL_2026_PIN_UPS.xlsx")
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from lmsr import LMSR

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    name TEXT PRIMARY KEY, balance REAL NOT NULL, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS markets (
    id INTEGER PRIMARY KEY, country TEXT NOT NULL, code TEXT NOT NULL, label TEXT NOT NULL,
    title TEXT NOT NULL, ref_month TEXT NOT NULL, cuts TEXT NOT NULL, outcomes TEXT NOT NULL,
    b REAL NOT NULL, prior TEXT NOT NULL, q TEXT NOT NULL, closes TEXT NOT NULL,
    void_after TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open',
    outcome INTEGER, settled_value REAL, settlement_source TEXT, created TEXT NOT NULL,
    UNIQUE (country, code, ref_month));
CREATE TABLE IF NOT EXISTS positions (
    account TEXT NOT NULL, market_id INTEGER NOT NULL, outcome INTEGER NOT NULL,
    shares REAL NOT NULL, PRIMARY KEY (account, market_id, outcome));
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY, ts TEXT NOT NULL, account TEXT NOT NULL, market_id INTEGER NOT NULL,
    outcome INTEGER NOT NULL, shares REAL NOT NULL, cost REAL NOT NULL, prices_after TEXT NOT NULL);
"""


class ExchangeError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Exchange:
    def __init__(self, path: str | Path = ":memory:", starting_points: float = 1000.0):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), timeout=10, check_same_thread=False)
        if str(path) != ":memory:":
            self.db.execute("PRAGMA journal_mode=WAL")   # readers do not block the writer
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.starting_points = starting_points

    def close(self) -> None:
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------ accounts --
    def open_account(self, name: str) -> None:
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO accounts VALUES (?, ?, ?)",
                            (name, self.starting_points, _now()))

    def balance(self, name: str) -> float:
        row = self.db.execute("SELECT balance FROM accounts WHERE name = ?", (name,)).fetchone()
        if row is None:
            raise ExchangeError(f"no account {name!r}")
        return row["balance"]

    # ------------------------------------------------------------- markets --
    def create_market(self, country: str, code: str, label: str, title: str, ref_month: str,
                      cuts: list[float], outcomes: list[str], prior, b: float,
                      closes: str, void_after: str) -> int:
        mm = LMSR(prior, b)
        with self.db:
            cur = self.db.execute(
                "INSERT OR IGNORE INTO markets (country, code, label, title, ref_month, cuts, outcomes,"
                " b, prior, q, closes, void_after, created) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (country, code, label, title, ref_month, json.dumps(cuts), json.dumps(outcomes),
                 b, json.dumps(mm.prior.tolist()), json.dumps(mm.q.tolist()), closes, void_after, _now()))
        if cur.rowcount == 0:
            raise ExchangeError(f"market {country}/{code}/{ref_month} already exists")
        return cur.lastrowid

    def market(self, market_id: int) -> dict:
        row = self.db.execute("SELECT * FROM markets WHERE id = ?", (market_id,)).fetchone()
        if row is None:
            raise ExchangeError(f"no market {market_id}")
        m = dict(row)
        for k in ("cuts", "outcomes", "prior", "q"):
            m[k] = json.loads(m[k])
        m["prices"] = LMSR(m["prior"], m["b"], m["q"]).prices().tolist()
        return m

    def markets(self, status: str | None = None, country: str | None = None) -> list[dict]:
        sql, args = "SELECT id FROM markets WHERE 1=1", []
        if status:
            sql += " AND status = ?"; args.append(status)
        if country:
            sql += " AND country = ?"; args.append(country)
        return [self.market(r["id"]) for r in self.db.execute(sql + " ORDER BY ref_month, code", args)]

    # -------------------------------------------------------------- trading --
    def quote(self, market_id: int, outcome: int, shares: float) -> float:
        m = self.market(market_id)
        return LMSR(m["prior"], m["b"], m["q"]).quote(outcome, shares)

    def trade(self, account: str, market_id: int, outcome: int, shares: float,
              now: str | None = None) -> float:
        """Buy (shares > 0) or sell (shares < 0) outcome shares at the LMSR price."""
        now = now or _now()
        m = self.market(market_id)
        if m["status"] != "open" or now >= m["closes"]:
            raise ExchangeError(f"market {market_id} is closed to trading")
        if not 0 <= outcome < len(m["outcomes"]):
            raise ExchangeError(f"outcome must be 0..{len(m['outcomes']) - 1}")
        held = self.db.execute("SELECT shares FROM positions WHERE account=? AND market_id=? AND outcome=?",
                               (account, market_id, outcome)).fetchone()
        held = held["shares"] if held else 0.0
        if shares < 0 and -shares > held + 1e-9:
            raise ExchangeError(f"cannot sell {-shares:g}; {account} holds {held:g}")
        mm = LMSR(m["prior"], m["b"], m["q"])
        cost = mm.quote(outcome, shares)
        if cost > self.balance(account) + 1e-9:
            raise ExchangeError(f"{account} has {self.balance(account):.2f} points; trade costs {cost:.2f}")
        mm.trade(outcome, shares)
        with self.db:
            self.db.execute("UPDATE accounts SET balance = balance - ? WHERE name = ?", (cost, account))
            self.db.execute("UPDATE markets SET q = ? WHERE id = ?", (json.dumps(mm.q.tolist()), market_id))
            self.db.execute(
                "INSERT INTO positions VALUES (?,?,?,?) ON CONFLICT(account, market_id, outcome)"
                " DO UPDATE SET shares = shares + excluded.shares", (account, market_id, outcome, shares))
            self.db.execute("INSERT INTO trades (ts, account, market_id, outcome, shares, cost, prices_after)"
                            " VALUES (?,?,?,?,?,?,?)",
                            (now, account, market_id, outcome, shares, cost, json.dumps(mm.prices().tolist())))
        return cost

    # ----------------------------------------------------------- settlement --
    def settle(self, market_id: int, value: float, source: str) -> int:
        """Pay 1 point per share of the winning bucket. Returns the winning outcome."""
        m = self.market(market_id)
        if m["status"] in ("settled", "void"):
            raise ExchangeError(f"market {market_id} already {m['status']}")
        outcome = int(np.searchsorted(np.asarray(m["cuts"]), value, side="right"))
        with self.db:
            for p in self.db.execute("SELECT account, shares FROM positions WHERE market_id=? AND outcome=?",
                                     (market_id, outcome)).fetchall():
                self.db.execute("UPDATE accounts SET balance = balance + ? WHERE name = ?",
                                (p["shares"], p["account"]))
            self.db.execute("UPDATE markets SET status='settled', outcome=?, settled_value=?, settlement_source=?"
                            " WHERE id=?", (outcome, value, source, market_id))
        return outcome

    def void(self, market_id: int, reason: str) -> None:
        """No official print in time: refund every account's net spend on this market."""
        with self.db:
            for r in self.db.execute("SELECT account, SUM(cost) AS spent FROM trades WHERE market_id=?"
                                     " GROUP BY account", (market_id,)).fetchall():
                self.db.execute("UPDATE accounts SET balance = balance + ? WHERE name = ?",
                                (r["spent"], r["account"]))
            self.db.execute("UPDATE markets SET status='void', settlement_source=? WHERE id=?",
                            (reason, market_id))

    # ---------------------------------------------------------- reporting --
    def leaderboard(self) -> list[dict]:
        """Cash balance plus open positions marked at current prices."""
        prices = {m["id"]: m["prices"] for m in self.markets(status="open")}
        out = []
        for a in self.db.execute("SELECT name, balance FROM accounts").fetchall():
            mtm = sum(p["shares"] * prices[p["market_id"]][p["outcome"]]
                      for p in self.db.execute("SELECT * FROM positions WHERE account=?", (a["name"],))
                      if p["market_id"] in prices)
            out.append({"account": a["name"], "balance": round(a["balance"], 2),
                        "open_value": round(mtm, 2), "total": round(a["balance"] + mtm, 2)})
        return sorted(out, key=lambda r: -r["total"])

    def price_history(self, market_id: int) -> list[dict]:
        m = self.market(market_id)
        hist = [{"ts": m["created"], "prices": m["prior"]}]
        for r in self.db.execute("SELECT ts, prices_after FROM trades WHERE market_id=? ORDER BY id", (market_id,)):
            hist.append({"ts": r["ts"], "prices": json.loads(r["prices_after"])})
        return hist
