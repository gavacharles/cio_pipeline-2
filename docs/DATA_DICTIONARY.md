# panel_v1.0 — Data Dictionary

Wide monthly panel, one row per month (DatetimeIndex `date`, month-start).
Values are index numbers (spliced across UBOS rebasings) or macro levels.

## CIPI material sub-indices (source: UBOS CIPI Excel tables)
| Column      | Meaning                                   |
|-------------|-------------------------------------------|
| CEM         | Cement                                    |
| IRONSTEEL   | Iron and steel (combined, as UBOS reports)|
| ALU         | Aluminium                                 |
| COPPER      | Copper                                    |
| SAND        | Sand                                      |
| CLAY        | Clay                                      |
| MURRAM      | Murram                                    |
| AGG         | Aggregate / hardcore                      |
| PAINT       | Paints and varnishes                      |
| TIMBER      | Timber                                    |
| BITUMEN     | Bitumen                                   |
| FUEL        | Fuel / diesel                             |
| PIPES       | Pipes                                     |
| NAILS/BOLTS/SCREWS | Fasteners (as separately reported) |
| LABOUR      | Labour cost series (where published)      |

## CIPI aggregates (source: UBOS)
| Column     | Meaning                              |
|------------|--------------------------------------|
| CIPI_ALL   | Overall Construction Input Price Index (headline) |
| CIPI_MAT   | Materials aggregate                  |
| CIPI_BLDG  | Buildings sector index               |
| CIPI_CIVIL | Civil works sector index             |
| CIPI_RES / CIPI_NONRES | Residential / non-residential (if published) |

## Macro block (source: MoFPED portal via ugatsdb)
| Column            | Meaning                          | Upstream |
|-------------------|----------------------------------|----------|
| exchange_rate     | UGX/USD period-average           | BoU      |
| central_bank_rate | Central Bank Rate (CBR)          | BoU      |
| lending_rate      | Commercial bank lending rate     | BoU      |
| cpi               | Consumer Price Index (headline)  | UBOS/BoU |
| private_credit    | Private-sector credit            | BoU      |
| gdp_nominal       | Nominal GDP (quarterly→monthly)  | UBOS     |

## Global auxiliary block (`panel_v1.0_brent.csv` / `panel_v1.0_extended.csv`, source: FRED / NY Fed, not MoFPED)
| Column                       | Meaning                                        | Upstream |
|-------------------------------|-------------------------------------------------|----------|
| brent_crude_usd               | Brent crude oil spot, USD/barrel, monthly avg  | FRED POILBREUSDM (IMF Primary Commodity Prices) |
| iron_ore_usd                  | Iron ore spot, USD/metric ton, monthly avg     | FRED PIORECRUSDM (IMF Primary Commodity Prices) |
| gscpi_supply_chain_pressure   | Global Supply Chain Pressure Index (standardized z-score) | NY Fed Research GSCPI |

MoFPED's macro portal has no global commodity-benchmark or freight-pressure series; these nodes are appended by
`src/ingest/build_global_oil_block.py` (Brent) and `src/ingest/build_global_extension_block.py` (iron ore,
GSCPI) onto copies of `panel_v1.0.csv` rather than mixed into the canonical MoFPED-sourced macro block.
`panel_v1.0_extended.csv` = `panel_v1.0_brent.csv` + iron ore + GSCPI (all three external nodes together).

A regional peer comparator (Kenya/Tanzania construction price index) was investigated and not included —
see `docs/GLOBAL_DATA_CATALOG_2015_2026.md` for why (frequency mismatch: KNBS CIPI is quarterly, not monthly).

## Provenance companions (in data/processed/)
- `splice_log.csv` — every rebasing splice factor + non-overlap flags
- `coverage_report.csv` — first/last obs, n_obs, %missing per series
- `panel_manifest.json` — version, build time, dimensions, overall %missing
