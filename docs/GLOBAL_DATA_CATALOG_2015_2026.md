# Global Data Catalog (2015-2026)

Country focus: Uganda (UGA).

| Source | Provider | Dataset | Series | Variable | Frequency | Status | Message |
|---|---|---|---|---|---|---|---|
| MOFPED/BoU/UBOS via ugatsdb | ugatsdb | BOU_E | E_PERIOD_AVG_USD | exchange_rate_ugx_usd | monthly | empty | series absent in macro_block.csv |
| MOFPED/BoU via ugatsdb | ugatsdb | BOU_MMI | CBR | central_bank_rate | monthly | empty | series absent in macro_block.csv |
| MOFPED/BoU via ugatsdb | ugatsdb | BOU_I | LENDING_RATE | lending_rate | monthly | empty | series absent in macro_block.csv |
| MOFPED/UBOS via ugatsdb | ugatsdb | BOU_CPI | CPI_HEADLINE | cpi_headline | monthly | ok | 107 rows |
| MOFPED/BoU via ugatsdb | ugatsdb | BOU_PSC | PSC_TOTAL | private_sector_credit | monthly | empty | series absent in macro_block.csv |
| World Bank WDI | world_bank | WDI | PA.NUS.FCRF | wb_official_exchange_rate_lcu_per_usd | annual | failed | The read operation timed out |
| World Bank WDI | world_bank | WDI | FP.CPI.TOTL.ZG | wb_inflation_cpi_pct | annual | ok | 11 rows |
| World Bank WDI | world_bank | WDI | FR.INR.LEND | wb_lending_interest_rate_pct | annual | ok | 4 rows |
| World Bank WDI | world_bank | WDI | NE.CON.TOTL.KD.ZG | wb_household_consumption_growth_pct | annual | ok | 11 rows |
| IMF WEO | imf_weo | WEO | NGDP_RPCH | imf_real_gdp_growth_pct | annual | failed | HTTP Error 403: Forbidden |
| IMF WEO | imf_weo | WEO | PCPIPCH | imf_cpi_inflation_pct | annual | failed | HTTP Error 403: Forbidden |
| IMF WEO | imf_weo | WEO | LP | imf_population_mn | annual | failed | HTTP Error 403: Forbidden |
| ILO ILOSTAT | manual | ILOSTAT | UNE_TUNE_SEX_AGE_RT_A | ilo_unemployment_rate | annual | manual | manual-only source; series quoted in registry |
| UN Comtrade | manual | HS total trade | imports_exports_total | comtrade_total_trade_value_usd | annual | manual | manual-only source; series quoted in registry |
| UBOS datasets | manual | CIPI Excel Tables | CIPI_HEADLINE | ubos_cipi_headline | monthly | manual | manual-only source; series quoted in registry |
| UBOS datasets | manual | PPI Manufacturing and Utilities Excel Tables | PPI_MANUFACTURING | ubos_ppi_manufacturing | monthly | manual | manual-only source; series quoted in registry |
| UBOS datasets | manual | CPI Excel Tables | CPI_HEADLINE | ubos_cpi_headline | monthly | manual | manual-only source; series quoted in registry |
| FRED (IMF Primary Commodity Prices) | manual | POILBREUSDM | POILBREUSDM | brent_crude_usd | monthly | ok | 106/106 rows over panel window (2017-07 to 2026-04) |
| FRED (IMF Primary Commodity Prices) | manual | PIORECRUSDM | PIORECRUSDM | iron_ore_usd | monthly | ok | 106/106 rows over panel window; global iron ore benchmark, parallel to Brent for the IRON/IRONSTEEL/STEEL sub-indices |
| NY Fed Research (GSCPI) | manual | GSCPI Monthly Data | GSCPI | gscpi_supply_chain_pressure | monthly | ok | 106/106 rows over panel window; standardized global shipping/supply-chain pressure proxy (Uganda is landlocked; no domestic freight-cost series exists in this pipeline) |

Note on regional peer comparison (Kenya/Tanzania construction indices): investigated and **not included**.
KNBS (Kenya) publishes a Construction Input Price Index, but only **quarterly**, not monthly — forcing it
onto this monthly panel would mean holding it flat for 2 months then stepping, which would distort
volatility/spillover estimation rather than provide a clean comparison. FRED's Kenya CPI series
(`KENPCPIPCPPPT`) is annual, not monthly, and is a growth rate, not a level. No clean, freely-available,
monthly regional construction-price comparator was found; a genuine regional comparison would require either
manually transcribing KNBS's quarterly PDF releases and explicitly modeling the frequency mismatch, or
running a separate quarterly-frequency side analysis rather than folding it into this monthly node set.

Note on MoFPED coverage: the MoFPED Macro Data Portal (https://mepd.finance.go.ug/apps/macro-data-portal/,
verified live) exposes >5000 series across real/external/financial/fiscal sectors and BoP/trade tables, but
it does not publish a global oil benchmark price. Brent is therefore sourced externally from FRED series
POILBREUSDM (IMF Primary Commodity Prices, global Brent spot, USD/barrel) and treated as an auxiliary
global node alongside `exchange_rate`, not as a MoFPED-sourced series.

Artifacts:
- data/raw/global_series_registry.csv
- data/raw/global_macro_block.csv