"""
p6_svar.py  —  Paper P6 starter.
SVAR of macro shocks into aggregate construction input costs, with IRFs, FEVD,
and an asymmetry check (do depreciations pass through faster than appreciations?).
The estimated exchange-rate sensitivity is exported for P8's WMVI calibration.

Inputs : data/processed/panel_v1.0.parquet (aggregate CIPI + macro block)
Outputs: p6_irf.csv, p6_fevd.csv, p6_sensitivity_vector.json
"""
from __future__ import annotations
import json, numpy as np, pandas as pd
from statsmodels.tsa.api import VAR

MACRO = ["exchange_rate", "cpi", "central_bank_rate", "private_credit"]
TARGET = "CIPI_ALL"

def prepare(panel: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in MACRO if c in panel.columns] + [TARGET]
    df = panel[cols].apply(pd.to_numeric, errors="coerce")
    # work in log-differences for I(1) series; CBR in first difference
    out = pd.DataFrame(index=df.index)
    for c in cols:
        s = df[c]
        out[c] = (np.log(s).diff() if (s > 0).all() else s.diff())
    return out.dropna()

def run_svar(data: pd.DataFrame, lags: int = 2, horizon: int = 24):
    res = VAR(data).fit(lags)                    # Cholesky identification (recursive)
    irf = res.irf(horizon)
    fevd = res.fevd(horizon)
    irf_df = pd.DataFrame(irf.irfs[:, data.columns.get_loc(TARGET), :],
                          columns=data.columns)
    fevd_df = pd.DataFrame(fevd.decomp[data.columns.get_loc(TARGET)],
                           columns=data.columns)
    return res, irf_df, fevd_df

def asymmetry_check(data: pd.DataFrame) -> dict:
    """Split FX shocks into + / - and compare cumulative CIPI response signs."""
    fx = data["exchange_rate"]
    pos = data[fx > 0][TARGET].mean()
    neg = data[fx < 0][TARGET].mean()
    return {"mean_cipi_when_depreciation": float(pos),
            "mean_cipi_when_appreciation": float(neg),
            "asymmetry": float(pos - neg)}

if __name__ == "__main__":
    panel = pd.read_parquet("data/processed/panel_v1.0.parquet")
    data = prepare(panel)
    res, irf_df, fevd_df = run_svar(data)
    irf_df.to_csv("p6_irf.csv", index=False)
    fevd_df.to_csv("p6_fevd.csv", index=False)
    sens = {"exchange_rate_sensitivity": float(irf_df["exchange_rate"].sum()),
            "cpi_sensitivity": float(irf_df.get("cpi", pd.Series([0])).sum()),
            "asymmetry": asymmetry_check(data)}
    json.dump(sens, open("p6_sensitivity_vector.json", "w"), indent=2)
    print("P6 done. Sensitivity vector exported for P8.")
