"""
model.py — structural CIPI forecaster: macro drivers -> components -> UBOS weights.

Three layers, each estimated on data up to the forecast origin only:

1. MACRO. The primitive series behind the drivers (UGX/USD, Brent USD, iron ore USD,
   CPI, GSCPI) follow a VAR(1). Own lags are estimated freely; cross effects are ridge-
   shrunk toward zero, so the VAR cannot invent strong spill-overs from ~100 months.
2. COMPONENTS. For every index component c (config/forecast_model.yaml maps it to a group):
       r_c,t = a + rho * r_c,t-1 + sum_d [ b0_d * x_d,t + b1_d * mean(x_d,t-1..t-3) ] + e_c,t
   fitted with a Huber loss (one-off jumps such as 2022 are down-weighted) plus L2
   shrinkage. Drivers x are monthly 100*log changes (GSCPI: level, lags only).
3. AGGREGATION. Simulated component levels are recombined with the published weights
   (index_structure.Structure.aggregate), so headline and sector forecasts are coherent
   with their components by construction.

Uncertainty comes from a joint block bootstrap: each simulated month draws macro AND
component residuals from the same historical month, which keeps their co-movement.

    ForecastModel(cfg).fit(structure, macro_panel, origin)  -> fitted model
    .simulate(horizon, n_paths, scenario)                    -> component level paths [P, H, C]
    .aggregate_paths(paths, sheet)                           -> index level paths [P, H]
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import HuberRegressor

TAIL_FILL_MONTHS = 3       # a source that ends up to 3 months early is carried forward (e.g. fiscal data)


# ------------------------------------------------------------------ inputs --
def load_macro(cfg: dict, root) -> pd.DataFrame:
    """The macro panel plus any `extra_sources` (CSV files with a `date` column), joined by month."""
    from pathlib import Path
    root = Path(root)
    panel = pd.read_csv(root / cfg["macro_source"], parse_dates=["date"]).set_index("date")
    for f in cfg.get("extra_sources", []):
        extra = pd.read_csv(root / f, parse_dates=["date"]).set_index("date")
        extra.index = extra.index.to_period("M").to_timestamp()
        panel = panel.join(extra[[c for c in extra.columns if c not in panel.columns]], how="outer")
    return panel


def load_policy_events(cfg: dict, root) -> list[dict]:
    """Enacted measures with a known size from config/policy_events.yaml (see that file)."""
    from pathlib import Path
    import yaml
    pol = cfg.get("policy")
    if not pol:
        return []
    with open(Path(root) / pol["file"], encoding="utf-8") as fh:
        events = yaml.safe_load(fh)["events"]
    return [e for e in events if e.get("status") == "enacted" and e.get("pct") is not None]


def lag_only_drivers(cfg: dict) -> set[str]:
    """Indicator drivers (levels, year-on-year rates) enter with lags 1-3 only."""
    return {n for n, d in cfg["drivers"].items() if d.get("transform", "dlog") != "dlog"}


def primitives(panel: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Macro primitives, transformed as their driver says:
    dlog  -> 100 * monthly log change (prices)
    level -> as published (indicators: GSCPI z-score, rainfall anomaly)
    yoy3  -> 100 * log(3-month sum / same 3 months a year earlier) (lumpy flows: public spending)"""
    out = {}
    for d in cfg["drivers"].values():
        for c in d["columns"]:
            s = pd.to_numeric(panel[c], errors="coerce")
            t = d.get("transform", "dlog")
            if t == "level":
                out[c] = s
            elif t == "yoy3":
                r3 = s.rolling(3).sum()
                out[c] = 100 * np.log(r3 / r3.shift(12))
            else:
                out[c] = 100 * np.log(s).diff()
            # a value for month t is only known `publication_lag` months later
            out[c] = out[c].shift(d.get("publication_lag", 0))
    P = pd.DataFrame(out)
    P = P.loc[P.dropna(how="all").index.min():P.dropna(how="all").index.max()]
    return P.ffill(limit=TAIL_FILL_MONTHS).dropna()


def drivers_from_primitives(prim: pd.DataFrame | np.ndarray, cfg: dict, columns: list[str]):
    """Each driver is the sum of its columns' primitives (e.g. oil = Brent USD + UGX/USD)."""
    names = list(cfg["drivers"])
    idx = {c: i for i, c in enumerate(columns)}
    if isinstance(prim, pd.DataFrame):
        return pd.DataFrame({n: sum(prim[c] for c in cfg["drivers"][n]["columns"]) for n in names})
    return np.stack([sum(prim[..., idx[c]] for c in cfg["drivers"][n]["columns"]) for n in names], axis=-1)


def group_of(label: str, cfg: dict) -> str:
    for g, spec in cfg["groups"].items():
        if any(m in label for m in spec["match"]):
            return g
    raise KeyError(f"component {label!r} matches no group in forecast_model.yaml")


def _features(own_prev: np.ndarray, X: np.ndarray, t: int, drv_idx: list[int], level_drv: set[int],
              month: int = 0, cal_months: tuple = ()):
    """Feature row(s) at time t from driver array X[..., time, driver] (lags must exist),
    plus one dummy per calendar month in `cal_months` (policy calendar: budget, wage rounds)."""
    cols = [own_prev]
    for d in drv_idx:
        if d not in level_drv:
            cols.append(X[..., t, d])
        cols.append(X[..., t - 3:t, d].mean(axis=-1))
    for cm in cal_months:
        cols.append(np.full(np.shape(own_prev), float(month == cm)))
    return np.stack(cols, axis=-1)


# ------------------------------------------------------------------ macro --
class MacroVAR:
    def __init__(self, ridge: float):
        self.ridge = ridge

    def fit(self, P: pd.DataFrame) -> "MacroVAR":
        Y, X = P.values[1:], P.values[:-1]
        mu, sd = X.mean(0), X.std(0) + 1e-12
        Z = np.c_[np.ones(len(X)), (X - mu) / sd]
        k = P.shape[1]
        A, c = np.zeros((k, k)), np.zeros(k)
        for j in range(k):
            pen = np.full(k + 1, self.ridge); pen[0] = 0.0; pen[1 + j] = 0.0
            b = np.linalg.solve(Z.T @ Z + np.diag(pen), Z.T @ Y[:, j])
            A[j] = b[1:] / sd
            c[j] = b[0] - (b[1:] / sd) @ mu
        # keep the VAR stable: shrink if the spectral radius is >= 0.98
        rad = np.abs(np.linalg.eigvals(A)).max()
        if rad >= 0.98:
            A *= 0.98 / rad
        self.A, self.c, self.columns = A, c, list(P.columns)
        self.resid = pd.DataFrame(Y - (c + X @ A.T), index=P.index[1:], columns=P.columns)
        self.last = P.values[-1]
        self.history = P
        return self

    def simulate(self, H: int, shocks: np.ndarray, add: np.ndarray | None = None,
                 replace: np.ndarray | None = None) -> np.ndarray:
        """shocks [P, H, k] residual draws; `add` [H, k] deterministic scenario shocks;
        `replace` [H, k] (NaN = keep) overrides the path, e.g. a historical replay."""
        Pn, k = shocks.shape[0], len(self.columns)
        out = np.empty((Pn, H, k))
        prev = np.repeat(self.last[None], Pn, axis=0)
        for h in range(H):
            x = self.c + prev @ self.A.T + shocks[:, h]
            if add is not None:
                x = x + add[h]
            if replace is not None:
                m = ~np.isnan(replace[h])
                x[:, m] = replace[h][m]
            out[:, h] = x
            prev = x
        return out


# -------------------------------------------------------------- components --
class ComponentModel:
    def __init__(self, label: str, drivers: list[str], all_drivers: list[str], cfg: dict):
        self.label, self.drivers = label, drivers
        self.drv_idx = [all_drivers.index(d) for d in drivers]
        self.lag_only = lag_only_drivers(cfg)
        self.level_drv = {all_drivers.index(d) for d in all_drivers if d in self.lag_only}
        m = cfg["model"]
        self.eps, self.alpha, self.bounds = m["huber_epsilon"], m["ridge_alpha"], m["own_lag_bounds"]
        self.cal = tuple(m.get("calendar_months", []))

    def fit(self, r: pd.Series, D: pd.DataFrame) -> "ComponentModel":
        dates = r.index.intersection(D.index)
        X = D.loc[D.index.min():dates.max()].values
        t_of = {d: i for i, d in enumerate(D.loc[D.index.min():dates.max()].index)}
        rows, ys, used = [], [], []
        for d in dates:
            t = t_of[d]
            prev = r.index.get_loc(d) - 1
            if t < 3 or prev < 0:
                continue
            rows.append(_features(np.array(r.iloc[prev]), X, t, self.drv_idx, self.level_drv, d.month, self.cal))
            ys.append(r.loc[d]); used.append(d)
        F, y = np.array(rows), np.array(ys)
        self.mu, self.sd = F.mean(0), F.std(0) + 1e-9
        if np.std(y) < 1e-9:                      # never changes in sample: carry it flat
            self.coef, self.intercept = np.zeros(F.shape[1]), float(y.mean())
        else:
            hub = HuberRegressor(epsilon=self.eps, alpha=self.alpha, max_iter=500)
            hub.fit((F - self.mu) / self.sd, y)
            raw = hub.coef_ / self.sd
            self.intercept = float(hub.intercept_ - raw @ self.mu)
            clipped = float(np.clip(raw[0], *self.bounds))
            self.intercept -= (clipped - raw[0]) * self.mu[0]   # keep the fit at the sample mean
            raw[0] = clipped
            self.coef = raw
        self.resid = pd.Series(y - (self.intercept + F @ self.coef), index=used)
        self.last_r = float(r.iloc[-1])
        return self

    def names(self) -> list[str]:
        out = ["own_lag"]
        for d in self.drivers:
            out += ([] if d in self.lag_only else [f"{d}_lag0"]) + [f"{d}_lag1-3"]
        return out + [f"month_{cm:02d}" for cm in self.cal]


# ----------------------------------------------------------------- system --
class ForecastModel:
    def __init__(self, cfg: dict):
        self.cfg = cfg

    def fit(self, structure, macro_panel: pd.DataFrame, origin=None) -> "ForecastModel":
        cfg = self.cfg
        origin = pd.Timestamp(origin) if origin is not None else structure.levels.index.max()
        self.structure, self.origin = structure, origin
        lv = structure.levels.loc[:origin]
        self.last_levels = lv.iloc[-1].values
        R = 100 * np.log(lv).diff().iloc[1:]
        self.full_prim = primitives(macro_panel, cfg)
        prim = self.full_prim.loc[:origin]
        self.prim_cols = list(prim.columns)
        D = drivers_from_primitives(prim, cfg, self.prim_cols)
        self.driver_names = list(D.columns)
        self.var = MacroVAR(cfg["macro_simulation"]["var_ridge"]).fit(prim)
        self.prim_tail = prim.values[-3:]
        self.components = []
        for c in lv.columns:
            g = group_of(c, cfg)
            m = ComponentModel(c, cfg["groups"][g]["drivers"], self.driver_names, cfg).fit(R[c], D)
            m.group = g
            self.components.append(m)
        # joint residual matrix on common months (macro + components) for the block bootstrap
        common = self.var.resid.index
        for m in self.components:
            common = common.intersection(m.resid.index)
        self.boot_macro = self.var.resid.loc[common].values
        self.boot_comp = np.column_stack([m.resid.loc[common].values for m in self.components])
        return self

    # ------------------------------------------------------------ simulate --
    def _scenario(self, name: str, H: int):
        spec = self.cfg["scenarios"].get(name)
        if spec is None:
            raise KeyError(f"unknown scenario {name!r}; see forecast_model.yaml")
        k = len(self.prim_cols)
        add, offset, replace = np.zeros((H, k)), np.zeros((H, k)), None
        for drv, s in spec.items():
            if drv == "pass_through":
                continue
            if drv == "replay":
                window = self.full_prim.loc[s[0]:s[1]].values
                replace = np.full((H, k), np.nan)
                replace[:min(H, len(window))] = window[:H]
                continue
            col = self.prim_cols.index(self.cfg["drivers"][drv]["columns"][0])
            a, b = s["months"]
            n = b - a + 1
            for h in range(a - 1, min(b, H)):
                if "level" in s:      # level shift held for the window, not fed back through the VAR
                    offset[h, col] += s["level"]
                else:                 # cumulative change spread evenly over the window
                    add[h, col] += s["total"] / n
        return add, offset, replace

    def policy_shocks(self, H: int, pass_through: float) -> np.ndarray:
        """[H, C] one-off log-% shocks from enacted policy events in the forecast window."""
        out = np.zeros((H, len(self.components)))
        for e in getattr(self, "events", []):
            h = (pd.Period(str(e["date"]), "M") - self.origin.to_period("M")).n - 1
            if 0 <= h < H:
                for j, m in enumerate(self.components):
                    if any(k in m.label for k in e["match"]):
                        out[h, j] += 100 * np.log(1 + e["pct"] * pass_through / 100)
        return out

    def simulate(self, H: int, n_paths: int | None = None, scenario: str = "baseline",
                 seed: int | None = None, macro_path: np.ndarray | None = None,
                 pass_through: float | None = None) -> np.ndarray:
        """Component level paths [P, H, C]. `macro_path` [H, k] fixes the macro primitives
        (e.g. realised values for an ex-post check) instead of simulating them."""
        ms = self.cfg["macro_simulation"]
        n_paths = n_paths or ms["n_paths"]
        rng = np.random.default_rng(ms["seed"] if seed is None else seed)
        T, B = len(self.boot_macro), ms["block_months"]
        n_blocks = int(np.ceil(H / B))
        starts = rng.integers(0, T - B + 1, size=(n_paths, n_blocks))
        draw = (starts[..., None] + np.arange(B)).reshape(n_paths, -1)[:, :H]
        u, e = self.boot_macro[draw], self.boot_comp[draw]           # [P, H, k], [P, H, C]
        if macro_path is not None:
            prim = np.repeat(macro_path[None], n_paths, axis=0)
        else:
            add, offset, replace = self._scenario(scenario, H)
            prim = self.var.simulate(H, u, add, replace) + offset
        full = np.concatenate([np.repeat(self.prim_tail[None], n_paths, axis=0), prim], axis=1)
        X = drivers_from_primitives(full, self.cfg, self.prim_cols)  # [P, 3+H, drivers]
        C = len(self.components)
        # drift uncertainty: each path shifts every component's mean change by the mean of a
        # bootstrap resample of the residual months minus the full-sample mean (common across
        # components, so trend errors are correlated as they are in the data)
        drift = np.zeros((n_paths, C))
        if ms.get("drift_uncertainty", True):
            res = rng.integers(0, T, size=(n_paths, T))
            drift = self.boot_comp[res].mean(axis=1) - self.boot_comp.mean(axis=0)
        if pass_through is None:
            pass_through = self.cfg["scenarios"].get(scenario, {}).get(
                "pass_through", self.cfg.get("policy", {}).get("baseline_pass_through", 0.0))
        pol = self.policy_shocks(H, pass_through) if macro_path is None else np.zeros((H, C))
        logs = np.empty((n_paths, H, C))
        months = [(self.origin + pd.DateOffset(months=h + 1)).month for h in range(H)]
        for j, m in enumerate(self.components):
            prev = np.full(n_paths, m.last_r)
            lvl = np.full(n_paths, np.log(self.last_levels[j]))
            for h in range(H):
                f = _features(prev, X, 3 + h, m.drv_idx, m.level_drv, months[h], m.cal)
                r = m.intercept + f @ m.coef + e[:, h, j] + drift[:, j] + pol[h, j]
                lvl = lvl + r / 100
                logs[:, h, j] = lvl
                prev = r
        return np.exp(logs)

    def aggregate_paths(self, paths: np.ndarray, sheet: str = "ALL") -> np.ndarray:
        w = self.structure.weights[sheet]
        cols = list(self.structure.levels.columns)
        wv = np.zeros(len(cols))
        for k, v in w.items():
            wv[cols.index(k)] = v
        return paths @ wv / wv.sum()

    def coefficients(self) -> pd.DataFrame:
        rows = []
        for m in self.components:
            for n, b in zip(m.names(), m.coef):
                rows.append({"component": m.label, "group": m.group, "term": n, "coef": b})
            rows.append({"component": m.label, "group": m.group, "term": "intercept", "coef": m.intercept})
        return pd.DataFrame(rows)
