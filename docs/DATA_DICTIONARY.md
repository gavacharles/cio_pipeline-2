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

## Provenance companions (in data/processed/)
- `splice_log.csv` — every rebasing splice factor + non-overlap flags
- `coverage_report.csv` — first/last obs, n_obs, %missing per series
- `panel_manifest.json` — version, build time, dimensions, overall %missing
