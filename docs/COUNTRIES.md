# Countries (status 22 October 2026)

Every country has a weekly note, price reports in its own currency, and weekly plus IMF-monthly
exchange rates. **Contracts and forecasts** need an official construction price series that
is published regularly.

| Country | Level | Official construction price series | Next step |
|---|---|---|---|
| Uganda | Contracts + structural forecast | UBOS CIPI, monthly (latest Apr 2026) | Refit when UBOS resumes |
| Kenya | Contracts + quarterly forecast | KNBS CIPI, quarterly PDF | More quarters, then a structural model |
| South Africa | Contracts (monthly) + nowcast | Stats SA P0151.1, monthly, 68 releases parsed (Jan 2021 – Aug 2026) | Driver-based model (rand, oil, steel) |
| Ghana | Reporting | GSS Prime Building Cost Index, monthly | Write the adapter, then contracts |
| Zimbabwe | Reporting | ZimStat BMPI / CEMPI, monthly | Write the adapter (the ZWG/USD currency situation needs care) |
| Senegal | Reporting | ANSD materials price index (IMC), monthly | Write the adapter |
| Mauritius | Reporting | Statistics Mauritius construction price index, quarterly | Write the adapter |
| Egypt | Reporting | CAPMAS building materials bulletin (last seen 2018) | Confirm it is current |
| Malawi | Reporting | NCIC / NSO construction cost indices (new) | Ask NCIC for the series |
| Namibia | Reporting | PPI for cement only; private First Capital index | Decide whether a private index can settle contracts |
| Ethiopia | Reporting | Planned 2020; status unknown | Ask ESS |
| Rwanda | Reporting | None (PPI coverage unconfirmed) | Ask NISR |
| Tanzania | Reporting | None current (NCC indices to 2020) | Ask NBS / NCC |
| Zambia, Botswana, Nigeria, Mozambique, Morocco | Reporting | None found | Crowd prices are the series |

**Adding a country:**
1. Write `config/countries/<key>.yaml`, with an `fx_code`.
2. For contracts, also write a settlement adapter (`settlement.load_releases` dispatches on
   `settlement.parser`) that returns one row per (release, series, period).
3. Choose a history rule: `newest_release`, `combine_releases` or `chain_first_prints`.

The weekly drivers, IMF history, notes, app and daily cycle then pick the country up automatically.
An index built from participants' own reports must never settle contracts, because participants
could move it.
