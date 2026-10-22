"""
structural.py — market opening probabilities from the structural forecaster (src/forecast/).

The market's contracts settle on one series' month-on-month % change. The structural
model simulates every CIPI component and re-aggregates with UBOS's weights, so it gives
a full distribution for any contract month, conditioned on macro drivers, rainfall,
public spending and known tax measures. This module turns those paths into bucket
probabilities and scores them against the market's own pooled nowcast.

    StructuralOpener(release, cfg_path).fit(origin)
        .probs(label, ref_month, cuts, floor) -> np.ndarray
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "forecast"))

from index_structure import read_release                                   # noqa: E402
from model import ForecastModel, load_macro, load_policy_events             # noqa: E402

SHEET_LABELS = {"overall construction index": "ALL"}   # market label -> index sheet


class StructuralOpener:
    def __init__(self, release: str | Path, cfg_path: str | Path | None = None, n_paths: int = 1000):
        self.cfg = yaml.safe_load(open(cfg_path or ROOT / "config" / "forecast_model.yaml", encoding="utf-8"))
        self.structure = read_release(release)
        self.macro = load_macro(self.cfg, ROOT)
        self.events = load_policy_events(self.cfg, ROOT)
        self.n_paths = n_paths

    def fit(self, origin=None, seed: int = 0) -> "StructuralOpener":
        self.model = ForecastModel(self.cfg).fit(self.structure, self.macro, origin)
        self.model.events = self.events
        self.seed = seed
        self._paths = {}
        return self

    def _series_paths(self, label: str, H: int) -> np.ndarray:
        if H not in self._paths:
            self._paths[H] = self.model.simulate(H, n_paths=self.n_paths, seed=self.seed)
        P = self._paths[H]
        if label in SHEET_LABELS:
            path = self.model.aggregate_paths(P, SHEET_LABELS[label])
            last = float(self.structure.published[SHEET_LABELS[label]].loc[self.model.origin])
        else:
            j = list(self.structure.levels.columns).index(label)
            path, last = P[:, :, j], float(self.structure.levels[label].loc[self.model.origin])
        return np.concatenate([np.full((len(path), 1), last), path], axis=1)

    def probs(self, label: str, ref_month, cuts: list[float], floor: float = 0.02) -> np.ndarray:
        ref = pd.Timestamp(ref_month).to_period("M")
        h = (ref - self.model.origin.to_period("M")).n
        if h < 1:
            raise ValueError(f"{ref} is not after the origin {self.model.origin:%Y-%m}")
        path = self._series_paths(label, h)
        mom = (path[:, h] / path[:, h - 1] - 1) * 100
        idx = np.searchsorted(np.asarray(cuts), np.round(mom, 2), side="right")
        p = np.bincount(idx, minlength=len(cuts) + 1).astype(float) / len(mom)
        k = len(p)
        floor = min(floor, 0.5 / k)
        return (1 - k * floor) * p + floor

    def has(self, label: str) -> bool:
        return label in SHEET_LABELS or label in self.structure.levels.columns
