# CiO construction-cost forecasting market: design

Date: 2026-10-21 · Code: `src/market/` · Config: `config/countries/` · Tests: `tests/test_market.py`

## 1. What it is, and what it is not

A place where contractors, quantity surveyors, developers and lenders state, by trading,
what they expect next month's construction input prices to do. It exists for two reasons:

- **Price discovery.** People who buy cement, steel and diesel every week often know about a
  price move before UBOS publishes it. Market prices pool that knowledge into a forecast
  that is updated continuously and is public.
- **Hedging, later.** Contractors lose margin when input prices move after a fixed-price bid.
  An index-linked contract that pays out when, say, rebar rises more than 1% in a month is a
  hedge. The tournament phase shows whether these contracts are understood, trusted and
  accurate before anyone offers them for money.

It is **not a betting product**. Contracts reference official statistics on input costs, not
events anyone can influence. There are deliberately no markets on tender awards, project
completion or named firms, because insiders could rig those.

## 2. Legal position (read before changing `regulation.mode`)

| Phase | Money | Status |
|---|---|---|
| 1. Tournament | Play money: points with no cash value, not purchasable or redeemable | **Current.** `country.validate` refuses any other mode |
| 2. Sandbox | Real-money index contracts | Needs a legal opinion, then an application to the Capital Markets Authority (CMA) Uganda regulatory sandbox |
| 3. Licensed | Cash-settled hedging contracts | Only on the regulator's terms |

Real-money contracts on a price index are likely to be **derivatives** (CMA). Real-money event
bets may be **gaming** (National Lotteries and Gaming Regulatory Board). Each new country has its
own regulators, listed in its config file.

## 3. Contract specification (Uganda)

| Field | Rule |
|---|---|
| Underlying | One UBOS CIPI series, identified by its exact UBOS row label (`config/countries/uganda.yaml`) |
| Quantity | Month-on-month % change in the reference month M |
| Settlement value | From the **first release whose latest month is M**, using that release's own values for M and M-1; rounded to 2 dp |
| Outcomes | Five buckets, `[lo, hi)`, outer buckets open-ended; materials have an explicit "unchanged" bucket |
| Payout | 1 point per share of the winning bucket |
| Trading closes | 00:00 UTC on the first day of M+1 |
| No release | Void if no first print within 120 days of the end of M; every account's net spend is refunded |
| Excluded | UBOS staff involved in CIPI price collection or compilation |
| Market maker | LMSR, liquidity b = 100, opening at the nowcast probabilities (floored at 2%) |

**Why changes, not levels, and why the first print.** Measured over the 10 releases in
`data/raw/` (`run_market.py revisions`, output `data/processed/market/revision_report.csv`):

- The 8 releases from September 2025 to April 2026 never revise a past month.
- The two older files (`CIPI_2020_06.xlsx`, `CIPI_2022_06_rebased.xlsx`) disagree with the current
  history by up to 9.8 percentage points of monthly change: UBOS's rebasing restated history.

Settling once, on the first print, means a later rebasing can never reopen a paid contract.
Computing the change inside one release means the base year does not matter.

**Why labels, not panel codes.** `parse_cipi.py` maps both "high tensile steel bars" and
"sheet steel, roofing sheets and similar" to `STEEL`, so the panel's `STEEL` column mixes the
two. It also maps "nails, bolts, screws…" to `IRON`. The market matches on the UBOS label and
lists rebar and roofing sheets as separate contracts. Fixing the parser would change the
research panel, so it is left for a separate decision.

## 4. Opening prices (the nowcast)

Each market opens at an equal-weight blend of a time-series model (drift, persistence,
seasonality, empirical residuals) and recent bucket frequencies, both weighted with a
24-month half-life (`src/market/nowcast.py`). The blend never opens a bucket below 2%.

Walk-forward backtest, 2021–2026, one and two months ahead
(`run_market.py backtest`, output `data/processed/market/backtest_metrics_uganda.csv`):

- It beats all-history bucket frequencies in **19 of 24** series × horizon cases.
- The gain is significant (Diebold–Mariano > 1.96) for **aggregate** and **sand**.
- It is worse for **labour** and **plastic pipes**. These are lumpy series (mostly
  "unchanged", occasional jumps); traders who know about wage rounds or import prices
  should correct it.
- The time-series model alone lost to bucket frequencies in most cases. The 50/50 weight was
  fixed, not tuned per series, but it was chosen after seeing these results. The tournament's
  own record is the true out-of-sample test.

**Structural opening prices.** `run_market.py compare-opening` also scores bucket probabilities
from the structural forecaster (`src/market/structural.py`, see `docs/FORECAST_MODEL.md`) and a
50/50 blend, on identical contract months at 1, 2 and 6 months ahead:

- The structural model wins on the overall index and sand.
- The blend wins on diesel, cement, aggregate and roofing sheets.
- The pooled nowcast stays best for the lumpy series (labour, pipes, timber, blocks, paint,
  rebar). There the structural model under-weights "unchanged".

Each contract's `opening` setting in `uganda.yaml` records its winner. Choosing by the same rule
on the first half of months still won on the second half (log loss 1.295 against 1.308 for
pooled everywhere), so the choice is not just fitted noise.

The operator's worst-case subsidy per market is `b · ln(1 / min prior)`: at most 100 · ln 50 ≈ 391 points.

## 5. Adding a country

1. Write `config/countries/<country>.yaml`: statistics office, release rules, regulators, contract list.
2. If the statistics office publishes in a new format, add a settlement adapter
   (`settlement.load_releases` dispatches on `settlement.parser`). It must return one row per
   (release file, series label, month), so first-print settlement works unchanged.
3. Run `backtest` and `revisions` for that country before opening markets.

Kenya (`kenya.yaml`) is stubbed as `planned`. KNBS publishes its Construction Input Price Index
**quarterly**, as PDF tables, so it needs a quarterly adapter, a quarter-on-quarter contract
and a quarterly nowcast. Rwanda and Tanzania come next, through the same steps.

## 6. Operating it

```bash
python src/ingest/pull_ubos_cipi.py --out data/raw/ubos_cipi_downloads   # keep releases current
python src/market/run_market.py settle --country uganda                  # pay out newly published months
python src/market/run_market.py open --country uganda                    # open the next month
python src/market/run_market.py board
python src/market/run_market.py leaderboard
```

The live ledger is `data/market/exchange.sqlite` (git-ignored). Every trade stores the post-trade
prices, so `Exchange.price_history` gives the crowd's forecast over time.

## 7. Open items

- **Stale data.** Releases on file end at April 2026, so contracts for October 2026 open six
  months ahead and their prices are close to plain frequencies. Harvest May–September 2026 first.
- **Web front end** for participants: accounts, trading, the board, the leaderboard. The ledger
  API in `src/market/ledger.py` is what it would call.
- **Participants.** Recruit through industry bodies (e.g. UNABCEC) and quantity-surveying firms.
- **Legal opinion** on phase 2 in Uganda.
- **Parser decision** on splitting `STEEL` and renaming `IRON` in the research panel.
