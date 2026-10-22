#!/usr/bin/env python3
"""
run_market.py — command line for the CiO construction-cost forecasting market.

    python src/market/run_market.py backtest --country uganda      # is the nowcast worth opening at?
    python src/market/run_market.py revisions --country uganda     # do UBOS releases revise past months?
    python src/market/run_market.py compare-opening                # pooled nowcast vs structural model
    python src/market/run_market.py open --country uganda          # open next month's contracts
    python src/market/run_market.py board                          # open markets: crowd vs model
    python src/market/run_market.py account NAME
    python src/market/run_market.py trade NAME MARKET_ID OUTCOME SHARES
    python src/market/run_market.py settle --country uganda        # settle from new releases, void stale ones
    python src/market/run_market.py leaderboard

Outputs: data/processed/market/backtest_{scores,metrics}_<country>.csv,
         data/processed/market/revision_report.csv,
         data/market/exchange.sqlite (git-ignored; the live ledger)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from country import load_country                                        # noqa: E402
from ledger import Exchange, ExchangeError                              # noqa: E402
from nowcast import mom_changes, predictive_probs, walk_forward, summarise, expected_change  # noqa: E402
from settlement import (load_releases, series_history, first_print, bucket_labels,  # noqa: E402
                        revision_report, period_step, history)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "processed" / "market"
DEFAULT_DB = ROOT / "data" / "market" / "exchange.sqlite"


def cmd_backtest(args) -> None:
    cfg = load_country(args.country)
    rel = load_releases(cfg)
    floor = cfg["exchange"]["probability_floor"]
    rows, scores = [], []
    freq, _ = period_step(cfg)
    min_train = cfg["exchange"].get("nowcast_min_train", 36)
    for m in cfg["markets"]:
        r = mom_changes(history(rel, m["label"], cfg))
        for h in args.horizons:
            s = walk_forward(r, m["cuts"], horizon=h, floor=floor, min_train=min_train)
            if s.empty:
                continue
            s.insert(0, "code", m["code"]); s.insert(1, "horizon", h)
            scores.append(s)
            rows.append({"code": m["code"], "horizon": h, **summarise(s)})
    OUT.mkdir(parents=True, exist_ok=True)
    pd.concat(scores).to_csv(OUT / f"backtest_scores_{cfg['key']}.csv", index=False)
    met = pd.DataFrame(rows)
    met.to_csv(OUT / f"backtest_metrics_{cfg['key']}.csv", index=False)
    print(met.to_string(index=False))
    print("\nlog_skill > 0 => opening prices beat all-history bucket frequencies; "
          "DM_stat > 1.96 => significantly.")


def cmd_revisions(args) -> None:
    rel = load_releases(load_country(args.country))
    rep = revision_report(rel)
    OUT.mkdir(parents=True, exist_ok=True)
    rep.to_csv(OUT / "revision_report.csv", index=False)
    n_rev = int((rep.spread_pp > 0.005).sum())
    print(f"{rel.source_file.nunique()} releases; {len(rep)} (series, month) changes printed more than once; "
          f"{n_rev} differ by more than 0.005 pp across releases (max {rep.spread_pp.max():.3f} pp).")


def cmd_compare_opening(args) -> None:
    """Score opening probabilities: pooled nowcast vs structural model vs their 50/50 pool,
    on identical contract months, walk-forward (each origin uses data up to itself only)."""
    import numpy as np
    from structural import StructuralOpener
    from settlement import bucket
    cfg = load_country(args.country)
    rel = load_releases(cfg)
    floor = cfg["exchange"]["probability_floor"]
    latest = rel[rel.release_month == rel.release_month.max()].source_file.iloc[0]
    rel_dir = next(Path(ROOT / d) for d in cfg["settlement"]["raw_dirs"] if (ROOT / d / latest).exists())
    opener = StructuralOpener(rel_dir / latest, n_paths=args.paths)
    markets = [m for m in cfg["markets"] if opener.has(m["label"])]
    hist = {m["code"]: series_history(rel, m["label"]) for m in markets}
    dates = opener.structure.levels.index
    rows = []
    for k, origin in enumerate(dates[48:-1]):
        opener.fit(origin, seed=k)
        for m in markets:
            lv = hist[m["code"]]
            r = mom_changes(lv.loc[:origin])
            for h in args.horizons:
                target = origin + pd.DateOffset(months=h)
                if target not in lv.index:
                    continue
                y = bucket(round((lv[target] / lv[target - pd.DateOffset(months=1)] - 1) * 100, 2), m["cuts"])
                pp = predictive_probs(r, target, m["cuts"], h, floor)
                ps = opener.probs(m["label"], target, m["cuts"], floor)
                pb = (pp + ps) / 2
                rows.append({"code": m["code"], "h": h, "target": target,
                             "pooled": -np.log(pp[y]), "structural": -np.log(ps[y]), "blend": -np.log(pb[y])})
    sc = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    sc.to_csv(OUT / "opening_comparison_scores.csv", index=False)
    met = sc.groupby(["code", "h"])[["pooled", "structural", "blend"]].mean().round(4)
    met.to_csv(OUT / "opening_comparison_metrics.csv")
    print(met.unstack("h").to_string())
    tot = sc.groupby("h")[["pooled", "structural", "blend"]].mean().round(4)
    print("\nmean log loss by horizon (lower is better):"); print(tot.to_string())
    print("\nbest per horizon:", tot.idxmin(axis=1).to_dict())


def _closes(ref: pd.Timestamp, cfg: dict) -> str:
    """Trading closes before prices are collected: end of the reference month (UBOS),
    or the 15th of the quarter's middle month, KNBS's price reference date."""
    if cfg["settlement"].get("trading_closes") == "mid_quarter_15th":
        return (ref + pd.DateOffset(months=1, days=14)).strftime("%Y-%m-%dT00:00:00Z")
    _, step = period_step(cfg)
    return (ref + pd.DateOffset(months=step)).strftime("%Y-%m-%dT00:00:00Z")


def cmd_open(args) -> None:
    cfg = load_country(args.country)
    rel = load_releases(cfg)
    latest = rel.release_month.max()
    freq, step = period_step(cfg)
    this_period = pd.Timestamp.now().to_period("Q" if step == 3 else "M").to_timestamp()
    ref = (pd.Timestamp(args.ref_month) if args.ref_month
           else max(latest + pd.DateOffset(months=step), this_period))
    horizon = ((ref.year - latest.year) * 12 + ref.month - latest.month) // step
    if horizon < 1:
        sys.exit(f"{ref:%Y-%m} is already published (latest release covers {latest:%Y-%m})")
    closes = _closes(ref, cfg)
    if closes <= pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"):
        sys.exit(f"{ref:%Y-%m} has already ended, so its market would open closed")
    if horizon > 2:
        print(f"warning: latest release on file covers {latest:%Y-%m}; opening {ref:%Y-%m} at horizon {horizon}. "
              "Harvest newer UBOS releases (src/ingest/pull_ubos_cipi.py) for sharper opening prices.")
    ex = Exchange(args.db, cfg["exchange"]["starting_points"])
    void_after = (ref + pd.DateOffset(months=step) + pd.Timedelta(days=cfg["settlement"]["void_after_days"])
                  ).strftime("%Y-%m-%dT00:00:00Z")
    opener = None
    if any(m["opening"] != "pooled" for m in cfg["markets"]):
        from structural import StructuralOpener
        src = rel[rel.release_month == latest].source_file.iloc[0]
        rel_dir = next(ROOT / d for d in cfg["settlement"]["raw_dirs"] if (ROOT / d / src).exists())
        opener = StructuralOpener(rel_dir / src).fit(latest)
    floor = cfg["exchange"]["probability_floor"]
    for m in cfg["markets"]:
        r = mom_changes(history(rel, m["label"], cfg, as_of=latest))
        prior = predictive_probs(r, ref, m["cuts"], horizon, floor)
        if m["opening"] != "pooled" and opener is not None and opener.has(m["label"]):
            ps = opener.probs(m["label"], ref, m["cuts"], floor)
            prior = ps if m["opening"] == "structural" else (prior + ps) / 2
        try:
            mid = ex.create_market(cfg["key"], m["code"], m["label"], m["title"], ref.strftime("%Y-%m"),
                                   m["cuts"], bucket_labels(m["cuts"]), prior,
                                   cfg["exchange"]["liquidity_b"], closes, void_after)
            print(f"opened #{mid} {m['code']:<10} {ref:%Y-%m} (h={horizon}, {m['opening']:<10})  "
                  + "  ".join(f"{p:.0%}" for p in prior))
        except ExchangeError as e:
            print(f"skip: {e}")


def cmd_board(args) -> None:
    ex = Exchange(args.db)
    for m in ex.markets(status="open", country=args.country):
        print(f"\n#{m['id']} {m['title']} — change in {m['ref_month']} (closes {m['closes'][:10]})")
        for i, (lab, p, p0) in enumerate(zip(m["outcomes"], m["prices"], m["prior"])):
            print(f"  [{i}] {lab:<28} crowd {p:6.1%}   model {p0:6.1%}")
        print(f"  implied mean change: crowd {expected_change(pd.Series(m['prices']).values, m['cuts']):+.2f}%"
              f"   model {expected_change(pd.Series(m['prior']).values, m['cuts']):+.2f}%")


def cmd_account(args) -> None:
    ex = Exchange(args.db)
    ex.open_account(args.name)
    print(f"{args.name}: {ex.balance(args.name):.2f} points")


def cmd_trade(args) -> None:
    ex = Exchange(args.db)
    try:
        cost = ex.trade(args.name, args.market_id, args.outcome, args.shares)
    except ExchangeError as e:
        sys.exit(str(e))
    m = ex.market(args.market_id)
    print(f"{args.name} {'bought' if args.shares > 0 else 'sold'} {abs(args.shares):g} x "
          f"'{m['outcomes'][args.outcome]}' for {cost:.2f} points; new price {m['prices'][args.outcome]:.1%}; "
          f"balance {ex.balance(args.name):.2f}")


def cmd_settle(args) -> None:
    cfg = load_country(args.country)
    rel = load_releases(cfg)
    ex = Exchange(args.db)
    now = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
    for m in ex.markets(country=cfg["key"]):
        if m["status"] in ("settled", "void"):
            continue
        fp = first_print(rel, m["label"], m["ref_month"], cfg["settlement"]["decimals"], period_step(cfg)[1])
        if fp:
            k = ex.settle(m["id"], fp["value"], f"{fp['source_file']} ({fp['note']})")
            print(f"settled #{m['id']} {m['code']} {m['ref_month']}: {fp['value']:+.2f}% -> '{m['outcomes'][k]}'"
                  f"  [{fp['source_file']}]")
        elif now >= m["void_after"]:
            ex.void(m["id"], f"no first print by {m['void_after'][:10]}")
            print(f"void #{m['id']} {m['code']} {m['ref_month']}: no release by {m['void_after'][:10]}")


def cmd_leaderboard(args) -> None:
    for i, r in enumerate(Exchange(args.db).leaderboard(), 1):
        print(f"{i:>3}. {r['account']:<20} {r['total']:>10.2f}  (cash {r['balance']:.2f}, open {r['open_value']:.2f})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(DEFAULT_DB))
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("backtest"); p.add_argument("--country", default="uganda")
    p.add_argument("--horizons", type=int, nargs="+", default=[1, 2]); p.set_defaults(fn=cmd_backtest)
    p = sub.add_parser("revisions"); p.add_argument("--country", default="uganda"); p.set_defaults(fn=cmd_revisions)
    p = sub.add_parser("compare-opening"); p.add_argument("--country", default="uganda")
    p.add_argument("--horizons", type=int, nargs="+", default=[1, 2, 6])
    p.add_argument("--paths", type=int, default=500); p.set_defaults(fn=cmd_compare_opening)
    p = sub.add_parser("open"); p.add_argument("--country", default="uganda")
    p.add_argument("--ref-month", help="YYYY-MM (default: month after the latest release)"); p.set_defaults(fn=cmd_open)
    p = sub.add_parser("board"); p.add_argument("--country"); p.set_defaults(fn=cmd_board)
    p = sub.add_parser("account"); p.add_argument("name"); p.set_defaults(fn=cmd_account)
    p = sub.add_parser("trade"); p.add_argument("name"); p.add_argument("market_id", type=int)
    p.add_argument("outcome", type=int); p.add_argument("shares", type=float); p.set_defaults(fn=cmd_trade)
    p = sub.add_parser("settle"); p.add_argument("--country", default="uganda"); p.set_defaults(fn=cmd_settle)
    p = sub.add_parser("leaderboard"); p.set_defaults(fn=cmd_leaderboard)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
