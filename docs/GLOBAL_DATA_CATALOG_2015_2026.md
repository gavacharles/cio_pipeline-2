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

Artifacts:
- data/raw/global_series_registry.csv
- data/raw/global_macro_block.csv