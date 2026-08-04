"""
p8_dam_simulator.py  —  Paper P8 (flagship) starter.
The Dynamic Adjustment Mechanism (DAM): a contract price-adjustment clause that
rebalances the contract sum when a Weighted Macro-Volatility Index (WMVI) breaches
calibrated trigger bands. Validated by SIMULATION on transparently stylised
reference projects (a road, a building, a water scheme) whose cost profiles are
built from CIPI material weights — NOT from real contract data.

Economics: under a fixed-price contract the contractor's margin erodes one-for-one
as input costs drift up. Under the DAM, when the WMVI breaches its trigger band the
contract sum is revised upward (capped per period); that revision is CUMULATIVE and
persists for the remainder of the contract, so the DAM tracks realised cost drift
and protects margin. The back-test compares margin level and variance, DAM vs fixed.

Inputs : data/processed/panel_v1.0.parquet ; p6_sensitivity_vector.json
Outputs: p8_backtest_results.csv
"""
from __future__ import annotations
import json, numpy as np, pandas as pd
from dataclasses import dataclass

REFERENCE_PROJECTS = {
    "road":     {"BITUMEN": .30, "AGG": .25, "FUEL": .15, "CEM": .10, "LABOUR": .20},
    "building": {"CEM": .25, "IRONSTEEL": .20, "SAND": .10, "TIMBER": .10,
                 "PAINT": .05, "LABOUR": .30},
    "water":    {"CEM": .20, "IRONSTEEL": .25, "PIPES": .25, "FUEL": .10, "LABOUR": .20},
}

@dataclass
class DAMConfig:
    trigger_z: float = 1.0        # WMVI z-score that triggers a contract-sum revision
    cap_per_period: float = 0.05  # max fractional upward revision per period
    duration_months: int = 18
    pass_through: float = 0.8     # share of drift the client agrees to absorb via DAM

def project_cost_index(panel: pd.DataFrame, weights: dict) -> pd.Series:
    """Weighted material cost index for the project basket (Laspeyres-style)."""
    mats = [m for m in weights if m in panel.columns]
    px = panel[mats].apply(pd.to_numeric, errors="coerce")
    w = pd.Series({m: weights[m] for m in mats}); w /= w.sum()
    return (px * w).sum(axis=1)

def build_wmvi(panel: pd.DataFrame, weights: dict, fx_sens: float = 1.0) -> pd.Series:
    mats = [m for m in weights if m in panel.columns]
    px = panel[mats].apply(pd.to_numeric, errors="coerce")
    ret = np.log(px).diff()
    w = pd.Series({m: weights[m] for m in mats}); w /= w.sum()
    wmvi = (ret.rolling(6).std() * w).sum(axis=1)
    if "exchange_rate" in panel:
        fx_vol = np.log(pd.to_numeric(panel["exchange_rate"], errors="coerce")).diff().rolling(6).std()
        wmvi = wmvi + abs(fx_sens) * fx_vol.reindex(wmvi.index).fillna(0)
    return (wmvi - wmvi.mean()) / wmvi.std()

def simulate(panel: pd.DataFrame, project: str, cfg: DAMConfig, fx_sens: float) -> dict:
    weights = REFERENCE_PROJECTS[project]
    cost = project_cost_index(panel, weights).dropna()
    wmvi = build_wmvi(panel, weights, fx_sens).reindex(cost.index).fillna(0)
    if len(cost) < cfg.duration_months:
        raise ValueError("panel too short for the chosen project duration")

    # pick the most volatile contiguous window as the stress test (the 2022 shock)
    roll = wmvi.rolling(cfg.duration_months).mean()
    end = roll.idxmax()
    end_i = cost.index.get_loc(end)
    start_i = max(0, end_i - cfg.duration_months + 1)
    idx = cost.index[start_i:end_i + 1]

    c0 = cost.loc[idx[0]]
    contract_sum = 1.0            # normalised; fixed-price contract sum
    dam_sum = 1.0                 # DAM contract sum, revised cumulatively
    fixed_margin, dam_margin, n_adj = [], [], 0
    for t in idx:
        realised_cost = cost.loc[t] / c0            # cost relative to award
        # fixed-price: margin = agreed sum - realised cost
        fixed_margin.append(contract_sum - realised_cost)
        # DAM: when volatility breaches the trigger, revise the sum upward toward
        # realised cost (capped, and only the agreed pass-through share)
        if wmvi.loc[t] > cfg.trigger_z:
            gap = max(0.0, realised_cost - dam_sum)
            revision = min(cfg.cap_per_period, cfg.pass_through * gap)
            dam_sum += revision                      # CUMULATIVE — persists onward
            if revision > 0:
                n_adj += 1
        dam_margin.append(dam_sum - realised_cost)

    fixed_margin = np.array(fixed_margin); dam_margin = np.array(dam_margin)
    return {"project": project,
            "window_start": str(idx[0].date()), "window_end": str(idx[-1].date()),
            "fixed_final_margin": round(float(fixed_margin[-1]), 4),
            "dam_final_margin": round(float(dam_margin[-1]), 4),
            "margin_protected": round(float(dam_margin[-1] - fixed_margin[-1]), 4),
            "fixed_margin_var": round(float(np.var(fixed_margin)), 6),
            "dam_margin_var": round(float(np.var(dam_margin)), 6),
            "n_adjustments": n_adj}

if __name__ == "__main__":
    panel = pd.read_parquet("data/processed/panel_v1.0.parquet")
    try:
        fx_sens = json.load(open("p6_sensitivity_vector.json"))["exchange_rate_sensitivity"]
    except Exception:
        fx_sens = 1.0
    cfg = DAMConfig()
    rows = [simulate(panel, p, cfg, fx_sens) for p in REFERENCE_PROJECTS]
    out = pd.DataFrame(rows)
    out.to_csv("p8_backtest_results.csv", index=False)
    print("P8 done. DAM vs fixed-price margin across stylised reference projects:")
    print(out.to_string(index=False))
    print("\nPositive 'margin_protected' = the DAM preserved contractor margin the "
          "fixed-price contract lost to input-cost drift.")
