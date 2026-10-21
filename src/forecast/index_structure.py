"""
index_structure.py — recover how UBOS builds the CIPI from one weighted release.

WHAT THE RELEASE PUBLISHES (verified on 06_2026CIPI_APRIL_2026_PIN_UPS.xlsx)
---------------------------------------------------------------------------
Four sheets (ALL CONSTRUCTION, 41 Buildings, 42 Civil engineering, 43 Specialised),
each a fixed-weight (Laspeyres) index, base period 2016/17 = 100, weights per 1000:

    sector index = (W_mat * Materials + W_util * Utilities + W_serv * Services + W_lab * Labour) / W_sector
    overall      = the same identity with the ALL-sheet weights (sector weights sum to 1000)

Each product's ALL-sheet weight is the sum of its sector weights, and a product has the
same index on every sheet it appears on. The listed "selected products" do not exhaust
the materials basket: about a third of the materials weight is unpublished. Because the
index is fixed-weight, that remainder's index is implied exactly:

    Hidden_t = (W_mat * Materials_t - sum_i w_i * P_i,t) / (W_mat - sum_i w_i)

So every published index is an exact weighted sum of named components plus one implied
"unpublished materials" component per sheet.

    read_release(path)         -> Structure (component levels, weights per sheet, published aggregates)
    Structure.aggregate(levels, sheet) -> rebuilt sector/overall index from component levels
    Structure.verify()         -> max reconstruction error per sheet (should be ~1e-12)
    Structure.contributions(sheet, start, end) -> each component's share of an index change
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import openpyxl

TOP_LEVEL = ("utilities", "services", "labour")
SHEET_KEYS = {"all construction": "ALL", "buildings": "BUILDINGS", "civil": "CIVIL", "specialised": "SPECIALISED"}


def _norm(s) -> str:
    return " ".join(str(s).split()).lower()


def _sheet_key(title: str) -> str | None:
    t = _norm(title)
    for k, v in SHEET_KEYS.items():
        if k in t:
            return v
    return None


@dataclass
class Structure:
    source_file: str
    levels: pd.DataFrame                       # month x component (product, hidden_<sheet>, utilities, ...)
    weights: dict[str, dict[str, float]]       # sheet -> component -> weight
    published: dict[str, pd.Series]            # sheet -> published overall index
    published_materials: dict[str, pd.Series] = field(default_factory=dict)

    def aggregate(self, levels: pd.DataFrame, sheet: str = "ALL") -> pd.Series:
        w = pd.Series(self.weights[sheet])
        return levels[w.index].mul(w, axis=1).sum(axis=1) / w.sum()

    def verify(self) -> dict[str, float]:
        return {s: float((self.aggregate(self.levels, s) - self.published[s]).abs().max())
                for s in self.weights}

    def contributions(self, sheet: str, start, end) -> pd.DataFrame:
        """Percentage-point contribution of each component to the change in `sheet` from start to end."""
        w = pd.Series(self.weights[sheet])
        a, b = self.levels.loc[pd.Timestamp(start), w.index], self.levels.loc[pd.Timestamp(end), w.index]
        base = float((w * a).sum())
        pp = w * (b - a) / base * 100
        return pd.DataFrame({"weight": w, "start": a, "end": b, "change_pct": (b / a - 1) * 100,
                             "contribution_pp": pp}).sort_values("contribution_pp")


def _read_sheet(ws) -> tuple[pd.DatetimeIndex, list[tuple]]:
    rows = list(ws.iter_rows(values_only=True))
    h = next(i for i, r in enumerate(rows) if r and any(_norm(c) == "weights" for c in r if c is not None))
    wcol = next(j for j, c in enumerate(rows[h]) if c is not None and _norm(c) == "weights")
    dcols = [j for j, c in enumerate(rows[h]) if j > wcol and c is not None]
    dates = pd.to_datetime([rows[h][j] for j in dcols]).to_period("M").to_timestamp()
    body = []
    for r in rows[h + 1:]:
        if len(r) <= wcol or r[wcol - 1] is None or r[wcol] is None:
            continue
        is_item = r[0] is not None and _norm(r[wcol - 1]) not in TOP_LEVEL
        body.append((_norm(r[wcol - 1]), float(r[wcol]), np.array([r[j] for j in dcols], dtype=float), is_item))
    return dates, body


def read_release(path: str | Path) -> Structure:
    path = Path(path)
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    comps: dict[str, np.ndarray] = {}
    weights: dict[str, dict[str, float]] = {}
    published, materials = {}, {}
    dates = None
    for ws in wb.worksheets:
        key = _sheet_key(ws.title)
        if key is None:
            continue
        dates, body = _read_sheet(ws)
        mat_w, mat_v, items, w = None, None, {}, {}
        for label, wt, vals, is_item in body:
            if is_item:
                items[label] = wt
                if label in comps and not np.allclose(comps[label], vals, equal_nan=True):
                    raise ValueError(f"{path.name}: {label!r} differs between sheets")
                comps[label] = vals
            elif label == "materials":
                mat_w, mat_v = wt, vals
            elif label in TOP_LEVEL:
                w[label] = wt
                comps[label] = vals
        top = body[-1]                                     # sheet total is the last weighted row
        hidden_w = mat_w - sum(items.values())
        hidden = f"unpublished materials ({key.lower()})"
        known = sum(wt * comps[k] for k, wt in items.items())
        comps[hidden] = (mat_w * mat_v - known) / hidden_w
        w.update(items)
        w[hidden] = hidden_w
        weights[key] = w
        published[key] = pd.Series(top[2], index=dates)
        materials[key] = pd.Series(mat_v, index=dates)
    if "ALL" not in weights:
        raise ValueError(f"{path.name}: no ALL CONSTRUCTION sheet with weights")
    levels = pd.DataFrame(comps, index=dates)
    return Structure(path.name, levels, weights, published, materials)


def latest_weighted_release(raw_dirs: list[str | Path]) -> Path:
    """Newest CIPI workbook (by latest month) that carries the weighted ALL CONSTRUCTION sheet."""
    best, best_month = None, None
    for d in raw_dirs:
        for f in Path(d).glob("*CIPI*.xls*"):
            try:
                s = read_release(f)
            except Exception:
                continue
            m = s.levels.index.max()
            if best_month is None or m > best_month:
                best, best_month = f, m
    if best is None:
        raise FileNotFoundError("no weighted CIPI release found")
    return best
