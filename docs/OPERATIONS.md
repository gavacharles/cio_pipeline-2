# Running the pilot: app, weekly note, monthly cycle, countries

## Forecaster, market, price reports: what each is for

| Piece | Answers | Knows | Speed |
|---|---|---|---|
| **Forecaster** (`src/forecast/`) | What should prices do, given public data? | Official indices, oil, exchange rates, CPI, rainfall, spending, tax measures | Updated weekly; official data arrives 1–3 months late |
| **Price reports** (`src/market/reports.py`) | What are people actually paying this week? | Participants' quotes and invoices | Weekly, in shillings per bag/bar/litre |
| **Market** (`src/market/`) | What do informed people expect the next official print to be? | Everything participants know, including what no dataset shows | Continuous until trading closes |

The forecaster is the base and the market opens at its prices. Participants move prices only when they
know something the model doesn't, so **the gap between crowd and model is the signal**. Over a few
rounds the record shows whose information beats the model, and by how much.

**Do you need the market?** Not on day one. The most useful products for contractors are the
**weekly note** and the **crowd price reports**. They need no regulator and work with a handful of
participants. The market adds value once 20–30 active participants trade, and it is the step toward
hedging contracts later. Run all three and judge the market on its record after 3–4 settled rounds.

## Participant app (`src/webapp/app.py`)

```bash
pip install -r requirements.txt
CIO_ADMIN_KEY=<secret> uvicorn --app-dir src/webapp app:app --host 0.0.0.0 --port 8000
```

- **Organiser:** open `/admin?key=<secret>`, create an invite code per person (name, organisation,
  country), and send it to them. Codes can be redeemed again on a new phone; the old login stops.
- **Participants:** enter the code, then:
  - **Contracts:** open contracts for their country, crowd vs model, trade with a live cost quote.
  - **Report prices:** the item, the price paid or quoted, and where. Medians of each person's
    reports, so repeated or wild reports can't move the series.
  - **Weekly note** and **Leaderboard**.
- **Storage:** one sqlite file, `data/market/exchange.sqlite` (git-ignored). Back it up daily.
- **Hosting:** any small Linux VM, behind HTTPS (e.g. Caddy or nginx), with the crontab below.
  Phones are the main client; the pages are built for 360-px screens.

## Automation (`src/market/cycle.py`, `deploy/crontab.example`)

| Job | When | What |
|---|---|---|
| `cycle.py daily` | 06:30 every day | Harvest UBOS and KNBS → settle any contract whose first print appeared → on a new UBOS release refit and re-forecast → open the next contracts. Idempotent |
| `cycle.py weekly` | Monday 05:00 | Refresh rainfall, Brent and UGX/KES/RWF → write `data/processed/notes/weekly_<date>.{md,html}` (the app shows the latest) |

Every step is logged to `data/market/cycle_log.csv`. A failed step is logged and the others still run.

## Weekly note (`src/forecast/weekly_note.py`)

The note works between official releases. It refits the structural model at the last UBOS release
and **conditions on the Brent and UGX/USD readings observed since then**
(`model.known_primitives`, from `build_weekly_drivers.py`). In the first note (22 Oct 2026):

- The shilling had weakened 13% in 13 weeks, and Brent was up 35% over the same period.
- That raised the expected January 2027 change in the overall index from +4.1% (no new data) to
  +5.6%, in diesel from +14% to +24%, and in rebar from +3.8% to +6.7%.

Contractors apply the expected % to their own last quote for the same item. Sections: drivers,
expected changes, crowd prices, open contracts, method. Note bands are the raw simulation 10–90%.
The backtest calibration (`interval_calibration.csv`) applies to `run_forecast.py forecast` output.

## Countries

| | Uganda | Kenya | Rwanda |
|---|---|---|---|
| Official index | UBOS CIPI, monthly Excel | KNBS CIPI, quarterly PDF | None (NISR PPI may cover construction; unconfirmed) |
| Contracts | 12, monthly | 7, quarterly; trading closes on the 15th of the quarter's middle month (KNBS price date) | None yet |
| Opening prices | Structural / blend / pooled per contract | Pooled nowcast (12 test quarters; mixed skill) | – |
| Forecaster | Full structural model | Not yet (26 quarters) | Not yet (no index) |
| Price reports and weekly drivers | Yes | Yes (KES) | Yes (RWF) |

**Kenya data:** `pull_knbs_cipi.py` and `parse_knbs_cipi.py`. 22 releases from Q1 2021 to Q2 2026; 16
have text tables, and six are scanned or have no readable tables. The six-quarter tables cover
Q4 2019–Q2 2026 except Q4 2021. No revisions across 2,228 repeated points, so history stitches
releases (`settlement.history: combine_releases`). KNBS publishes the full basket with weights,
so a Kenya structural model is possible once more quarters accumulate.

**Rwanda:** collect prices and run the note. Contracts wait until a settlement series is agreed:
confirm with NISR whether the PPI includes construction. An index built from participants' own
reports must not settle contracts, because participants could move it.

## Before inviting participants

- Legal: play money only (`regulation.mode` is enforced). Get a one-page opinion per country
  before any prize or cash element.
- Verify the cement excise in `config/policy_events.yaml` (the sources conflict).
- Set a strong `CIO_ADMIN_KEY` and serve over HTTPS.
