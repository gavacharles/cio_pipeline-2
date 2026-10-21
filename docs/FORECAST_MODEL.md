# Structural CIPI forecaster

Date: 2026-10-21 · Code: `src/forecast/` · Config: `config/forecast_model.yaml`,
`config/policy_events.yaml` · Tests: `tests/test_forecast.py` · Outputs: `data/processed/forecast/`

```bash
python src/ingest/build_rainfall_block.py       # refresh the rainfall driver (ERA5 via Open-Meteo)
python src/forecast/run_forecast.py structure   # rebuild the index from its published weights
python src/forecast/run_forecast.py backtest    # walk-forward evaluation + band calibration (~20 s)
python src/forecast/run_forecast.py forecast    # 18-month paths, calibrated 80% bands, all scenarios
python src/forecast/run_forecast.py stability   # pass-through estimates by estimation end date
# --config FILE --out DIR run any of these on a variant (how candidate drivers are tested)
```

## 1. How UBOS builds the index (recovered, not assumed)

The weighted workbook (`06_2026CIPI_APRIL_2026_PIN_UPS.xlsx`) has four sheets: All construction,
Buildings, Civil engineering and Specialised construction. Each is a fixed-weight index with
base period 2016/17 = 100:

    index = (W_materials · Materials + W_utilities · Utilities + W_services · Services + W_labour · Labour) / W_total

- The sector weights (421.1 + 96.9 + 482.0) sum to the overall 1000.
- Each product's overall weight is the sum of its sector weights.
- A product has the same index on every sheet it appears on.
- **The published products do not cover the whole materials basket.** 22 distinct products carry
  545 of the 803 materials weight points. Because the index is fixed-weight, the index of the
  unpublished remainder is implied exactly, per sheet. For the overall index it carries 336 points
  and is a smooth series: 100 at base, 122 in April 2026.

All four published indices rebuild from 29 components with an error of about 1e-13 index points
(`structure_check.csv`). Forecasts are made per component and re-aggregated with UBOS's weights,
so headline and sector forecasts always agree with their components. Rerun `structure` on the
first release after a UBOS rebasing, because the weights will change.

## 2. The model

| Layer | What | Why it is stable |
|---|---|---|
| Drivers | UGX/USD, Brent and iron ore in shillings, CPI, GSCPI, **rainfall anomaly**, **public-spending growth** | Each driver kept only if the backtest improved; publication lags respected |
| Macro | VAR(1) on the driver series | Cross-effects ridge-shrunk; spectral radius capped below 1 |
| Components | Monthly % change on own lag + group drivers | Huber loss down-weights one-off jumps (2022); L2 shrinkage; economically chosen driver groups |
| Policy | Known tax measures (`policy_events.yaml`) as one-off shocks × pass-through | Sourced events only; pass-through bracketed by scenarios |
| Aggregation | Published weights | Exact identity |
| Uncertainty | Joint 6-month block bootstrap of macro + component residuals, drift resampling, bands widened by backtest calibration | Calibrated 80% bands cover 80% of past outcomes |

Driver groups:

| Group | Components | Drivers |
|---|---|---|
| Fuel | diesel, bitumen | oil, fx |
| Steel | rebar, roofing, nails, pipes, doors and windows | ore, fx, GSCPI, fiscal |
| Binders | cement, lime | fx, oil, CPI, fiscal |
| Quarry | aggregate, sand, clay/murram, concrete blocks | oil, CPI, rain, fiscal |
| Imported | tiles, paints, plastic pipes, cables | fx, oil, GSCPI |
| Wood | timber, props | CPI |
| Unpublished materials | the implied remainder | fx, oil, CPI |
| Domestic | labour, services, utilities | CPI |

Price drivers enter at lag 0 and as the mean of lags 1–3. Indicator drivers (GSCPI, rainfall,
fiscal) enter at lags 1–3 only. Fiscal data is shifted by its 2-month publication lag.

## 3. Evidence (walk-forward, origins 2021-07 to 2026-03, refit at every origin)

RMSE of the cumulative % change, relative to an exponentially weighted drift (below 1 is better):

| Index, horizon | Structural | No change | Direct AR(1) | With actual macro | DM vs drift |
|---|---|---|---|---|---|
| Overall, 1 month | 0.87 | 1.14 | 0.97 | 0.86 | −1.7 |
| Overall, 3 months | 0.89 | 1.17 | 0.99 | 0.84 | −1.2 |
| Overall, 6 months | 0.89 | 1.18 | 0.99 | 0.81 | −1.3 |
| Overall, 12 months | 0.87 | 1.15 | 0.97 | 0.73 | −1.8 |
| Buildings, 12 months | 0.84 | 1.34 | 0.98 | 0.86 | −2.3 |
| Civil works, 3 months | 0.88 | 1.17 | 1.00 | 0.87 | −1.9 |
| Specialised, 1 month | 0.84 | 1.10 | 0.94 | 0.83 | −2.0 |

- The structural model beats drift, no-change and a direct AR(1) on every published index at
  every horizon. Significance is borderline (DM between −0.8 and −2.3).
- **The "with actual macro" column shows where the remaining error comes from.** Most of the
  12-month error is macro forecasting error, which is why the scenarios matter.
- Before calibration, bands cover 85% / 76% / 69% / 65% at 1 / 3 / 6 / 12 months. The forecast
  widens them by 1.00 / 1.06 / 1.16 / 1.17 (`interval_calibration.csv`).

**What was tested and what was kept.** Each candidate was run as a config variant through the
same backtest; mean RMSE is relative to the model without it, over 36 target × horizon cases.

| Candidate | Mean RMSE | Better in | Decision |
|---|---|---|---|
| Rainfall (quarry group) | −0.3% | 28 of 36 | **Kept** |
| Public-spending growth (steel, binders, quarry) | −0.9% | 26 of 36 | **Kept**. Civil works −4 to −5% at 1–3 months; rebar −4% |
| Both | −1.2% | 27 of 36 | **Kept** |
| July and January calendar effects on every component | +1.1% | 9 of 36 | **Rejected** (`calendar_months: []`) |

**Signs.** A wetter-than-usual quarter raises aggregate, sand and brick prices by about 0.16% a
month per standard deviation, consistent with interrupted supply. Faster public-spending growth
goes with slightly *lower* steel and quarry prices. That is not a demand effect: total spending
mixes in debt service and wages, so treat it as a statistical predictor until development
(capital) spending can be tested instead.

**Long-run pass-through** (response to a sustained 1% move; `stability.csv`):

| Effect | Estimate | Stable? |
|---|---|---|
| Diesel ← Brent in shillings | 0.11–0.14 | Yes |
| Diesel ← UGX/USD | 0.8–1.8 | Large but variable |
| Rebar ← iron ore | ≈ 0 | — |
| Cement ← UGX/USD | −0.5 to 0 | No |
| Unpublished basket ← CPI | −0.1 to +0.5 | No |

Rebar seems to follow local and scrap-based supply rather than world ore prices. The shrinkage
keeps the unstable effects small.

## 4. Known policy measures (`config/policy_events.yaml`)

| Date | Measure | Price effect at full pass-through | Applied? |
|---|---|---|---|
| Jul 2021 | Fuel excise +Shs100/l (diesel 1,030 → 1,130) | — | History only |
| Jul 2024 | Fuel excise +Shs100/l (diesel 1,130 → 1,230) | — | History only |
| Jul 2024 | Excise on white cement and lime | — | History only |
| Jul 2025 | Fuel excise rise proposed, then dropped | — | No |
| **Jul 2026** | **Fuel excise +Shs200/l** | Diesel +3.1% (pump price ~Shs6,500) | **Yes** |
| **Jul 2026** | **Cement excise per bag 500 → 750 or 1,000** (sources conflict) | Cement +1.2% (assumed ~Shs32,000 bag) | **Yes** |
| **Jul 2026** | **New excise on paints (3% local)** | Paint +3.0% | **Yes** |

History does not support assuming full pass-through. Diesel rose 6.7% in July 2021 (oil was also
rising) but fell 1.4% in July 2024. The baseline therefore applies 50%, and the
`policy_full_pass_through` and `policy_no_pass_through` scenarios bracket it. Two events cannot
support an estimated effect. Each further July in the data will help, and every source URL is in
the file for checking. The cement bag price is an assumption: no 2026 price was found.

## 5. Forecast from April 2026 (latest release on file)

Overall index 130.34 in April 2026. Baseline (including July 2026 taxes at 50% pass-through):

| Month | Median | Change | Calibrated 80% band |
|---|---|---|---|
| July 2026 | 133.2 | +2.2% | 132.3 – 134.8 |
| October 2026 | 134.4 | +3.1% | 132.8 – 138.2 |
| April 2027 | 136.9 | +5.0% | 133.4 – 143.9 |
| October 2027 | 139.5 | +7.0% | 134.3 – 148.2 |

Diesel is expected to rise about 17% by April 2027 and contributes 2.1 of the 5.0 points: oil
pass-through still to come plus the July excise.

Scenarios for April 2027:

| Scenario | Change |
|---|---|
| Baseline | +5.0% |
| Full / no pass-through of July taxes | +5.5% / +4.6% |
| Oil back to ~$70 | +3.4% |
| Oil +30% | +6.5% |
| Shilling 10% weaker | +6.8% |
| Supply-chain stress | +5.2% |
| 2022 replay | +5.7% |

**Evidence the baseline may be low for diesel.** Press reports put Kampala diesel at
Shs6,300–6,700 per litre in Q2 2026, against Shs5,000–5,500 earlier in the year. The April index
had diesel only about 7% above February. May–September 2026 releases will show whether the
index followed pump prices. Refit when they arrive; they are the first true out-of-sample test.

## 6. What else moves the index, and what is in the model now

The model explains about a quarter of month-to-month movement; over 12 months the macro channel
dominates (section 3).

| Factor | Status |
|---|---|
| Taxes and policy calendar | **In**, as sourced events (section 4). Blanket July/January effects were rejected |
| Weather | **In** (rainfall → quarry products) |
| Public demand | **In** (total spending growth). Development spending, if available, is the better test |
| Oil and gas project demand (EACOP, Tilenga, Kingfisher), roads, SGR | Not in; needs a project spending or activity series |
| Domestic supply (cement capacity, sand-mining rules, local steel mills, power tariffs) | Not in; candidates for the event file once dated |
| Logistics (Northern Corridor, Mombasa, fuel-import arrangements) | Partly via GSCPI; no local freight series |
| Measurement (fixed 2016/17 weights, carried-forward prices, rebasing) | Handled structurally: exact weights, empirical residuals that keep "unchanged" months, first-print settlement in the market |
| Market structure (few cement and steel producers; sticky, stepwise prices) | Visible in the residuals; not modelled |

Any new factor goes into `forecast_model.yaml` as a driver (or into `policy_events.yaml` as an
event) and stays only if `backtest` improves.
