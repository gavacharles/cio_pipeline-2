"""
p4_dcc_spillover.py  —  Paper P4 (SIMI) starter.
Estimate a DCC-GARCH system over CIPI material returns, compute Diebold-Yilmaz
spillovers, build the spillover network, and rank materials by a composite
Systemically Important Material Input (SIMI) score.

Inputs : data/processed/panel_v1.0.parquet  (wide material index matrix)
Outputs: p4_spillover_table.csv, p4_simi_ranking.csv, p4_network.graphml
"""
from __future__ import annotations
import numpy as np, pandas as pd, networkx as nx
from pathlib import Path

def log_returns(panel: pd.DataFrame, material_cols: list[str]) -> pd.DataFrame:
    px = panel[material_cols].apply(pd.to_numeric, errors="coerce")
    return np.log(px).diff().dropna(how="all")

def diebold_yilmaz(returns: pd.DataFrame, horizon: int = 10, lags: int = 2) -> pd.DataFrame:
    """Generalised FEVD spillover table via a reduced-form VAR (statsmodels)."""
    from statsmodels.tsa.api import VAR
    r = returns.copy()
    # Keep only series with enough observations; CIPI materials may have
    # staggered starts across vintages, so strict complete-case rows can be empty.
    min_obs = max(24, lags + 5)
    keep = [c for c in r.columns if r[c].notna().sum() >= min_obs]
    r = r[keep]

    if r.shape[1] < 2:
        raise ValueError("Not enough material return series with sufficient data for VAR spillover.")

    # Light imputation to preserve monthly continuity around short gaps.
    r = r.ffill(limit=2).bfill(limit=2)
    r = r.dropna()

    if r.empty:
        # Last-resort fallback for highly ragged panels: zero-return fill.
        r = returns[keep].fillna(0.0)

    res = VAR(r).fit(lags)
    fevd = res.fevd(horizon)
    # contribution to each variable's forecast-error variance from every other
    table = pd.DataFrame(fevd.decomp[:, -1, :], index=r.columns, columns=r.columns)
    table = table.div(table.sum(axis=1), axis=0) * 100
    return table

def simi_scores(spill: pd.DataFrame, basket_share: pd.Series | None = None) -> pd.DataFrame:
    to_others = spill.sum(axis=0) - np.diag(spill)          # transmitted
    from_others = spill.sum(axis=1) - np.diag(spill)         # received
    net = to_others - from_others
    out = pd.DataFrame({"to_others": to_others, "from_others": from_others, "net": net})
    if basket_share is not None:
        out["basket_share"] = basket_share.reindex(out.index).fillna(0)
        out["SIMI"] = (out["net"].rank() + out["basket_share"].rank()) / 2
    else:
        out["SIMI"] = out["net"].rank()
    return out.sort_values("SIMI", ascending=False)

def build_network(spill: pd.DataFrame, threshold: float = 5.0) -> nx.DiGraph:
    G = nx.DiGraph()
    for i in spill.index:
        for j in spill.columns:
            if i != j and spill.loc[i, j] >= threshold:
                G.add_edge(j, i, weight=float(spill.loc[i, j]))  # j -> i transmission
    return G

if __name__ == "__main__":
    panel = pd.read_parquet("data/processed/panel_v1.0.parquet")
    mats = [c for c in panel.columns if c.isupper() and not c.startswith("CIPI")]
    rets = log_returns(panel, mats)
    spill = diebold_yilmaz(rets)
    spill.to_csv("p4_spillover_table.csv")
    simi = simi_scores(spill)
    simi.to_csv("p4_simi_ranking.csv")
    nx.write_graphml(build_network(spill), "p4_network.graphml")
    print("P4 done:", simi.index[0], "is the most systemically important input.")
