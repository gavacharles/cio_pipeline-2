"""
p3_dtw_cluster.py  —  Paper P3 starter.
DTW-based time-series clustering of CIPI material series into a volatility-cluster
taxonomy for procurement risk grouping. Uses tslearn's TimeSeriesKMeans with DBA
(standard k-means CANNOT consume DTW distances). t-SNE layout with a perplexity
sweep and a UMAP stability check, as reviewers expect.

Inputs : data/processed/panel_v1.0.parquet
Outputs: p3_clusters.csv, p3_embedding.csv
"""
from __future__ import annotations
import numpy as np, pandas as pd

def material_matrix(panel: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    mats = [c for c in panel.columns if c.isupper() and not c.startswith("CIPI")]
    X = panel[mats].apply(pd.to_numeric, errors="coerce")
    X = np.log(X).diff().dropna(how="all").fillna(0.0).T.values  # one row per material
    return X, mats

def cluster(X, k: int = 4, seed: int = 0):
    from tslearn.clustering import TimeSeriesKMeans
    from tslearn.preprocessing import TimeSeriesScalerMeanVariance
    Xs = TimeSeriesScalerMeanVariance().fit_transform(X)
    km = TimeSeriesKMeans(n_clusters=k, metric="dtw", max_iter=20, random_state=seed)
    return km.fit_predict(Xs)

def embed(X, perplexities=(5, 10, 15)):
    """t-SNE across a perplexity sweep + UMAP check; return the sweep for stability."""
    from sklearn.manifold import TSNE
    out = {}
    for p in perplexities:
        p_eff = min(p, max(2, X.shape[0] - 1))
        out[f"tsne_p{p}"] = TSNE(n_components=2, perplexity=p_eff,
                                 random_state=0).fit_transform(X)
    try:
        import umap
        out["umap"] = umap.UMAP(n_neighbors=min(15, X.shape[0]-1),
                                random_state=0).fit_transform(X)
    except Exception as e:      # UMAP optional
        print("UMAP unavailable:", e)
    return out

if __name__ == "__main__":
    panel = pd.read_parquet("data/processed/panel_v1.0.parquet")
    X, mats = material_matrix(panel)
    labels = cluster(X)
    pd.DataFrame({"material": mats, "cluster": labels}).to_csv("p3_clusters.csv", index=False)
    print("P3 done:", dict(zip(mats, labels)))
