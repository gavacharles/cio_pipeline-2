"""
test_forecast.py
================
Tests for the structural CIPI forecaster (src/forecast/). Run with:  pytest -q

They assert:
(a) the published indices rebuild exactly from components and weights;
(b) fitting at an origin uses no data after it (no look-ahead);
(c) simulated paths are coherent: sector paths are weighted sums of component paths;
(d) scenario shocks have the intended size (level shifts do not compound).
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "forecast"))

from index_structure import read_release        # noqa: E402
from model import ForecastModel, load_macro      # noqa: E402

RELEASE = ROOT / "data" / "raw" / "06_2026CIPI_APRIL_2026_PIN_UPS.xlsx"
pytestmark = pytest.mark.skipif(not RELEASE.exists(), reason="April 2026 CIPI release not on disk")


@pytest.fixture(scope="module")
def setup():
    cfg = yaml.safe_load(open(ROOT / "config" / "forecast_model.yaml"))
    cfg["macro_simulation"]["n_paths"] = 200
    s = read_release(RELEASE)
    macro = load_macro(cfg, ROOT)
    return cfg, s, macro


def test_structure_rebuilds_published_indices(setup):
    _, s, _ = setup
    assert set(s.weights) == {"ALL", "BUILDINGS", "CIVIL", "SPECIALISED"}
    assert max(s.verify().values()) < 1e-9
    assert abs(sum(s.weights["ALL"].values()) - 1000) < 1e-6
    # each product's overall weight is the sum of its sector weights
    sectors = [s.weights[k] for k in ("BUILDINGS", "CIVIL", "SPECIALISED")]
    assert abs(sum(w.get("cement", 0) for w in sectors) - s.weights["ALL"]["cement"]) < 1e-9


def test_fit_has_no_lookahead(setup):
    cfg, s, macro = setup
    origin = pd.Timestamp("2022-12-01")
    a = ForecastModel(cfg).fit(s, macro, origin).coefficients()
    s2 = read_release(RELEASE)
    s2.levels.loc[s2.levels.index > origin] *= 1.5          # corrupt the future
    macro2 = macro.copy()
    macro2.loc[macro2.index > origin] *= 2.0
    b = ForecastModel(cfg).fit(s2, macro2, origin).coefficients()
    assert np.allclose(a.coef.values, b.coef.values)


def test_paths_are_coherent_and_start_from_origin(setup):
    cfg, s, macro = setup
    m = ForecastModel(cfg).fit(s, macro)
    P = m.simulate(6, n_paths=200, seed=1)
    assert P.shape == (200, 6, s.levels.shape[1]) and np.isfinite(P).all()
    agg = m.aggregate_paths(P, "ALL")
    manual = sum(P[:, :, list(s.levels.columns).index(c)] * w for c, w in s.weights["ALL"].items()) / 1000
    assert np.allclose(agg, manual)
    # one month ahead stays near the last published value
    assert abs(np.median(agg[:, 0]) / s.published["ALL"].iloc[-1] - 1) < 0.03


def test_scenarios_have_intended_size(setup):
    cfg, s, macro = setup
    m = ForecastModel(cfg).fit(s, macro)
    add, offset, _ = m._scenario("supply_chain_stress", 12)
    g = m.prim_cols.index("gscpi_supply_chain_pressure")
    assert np.allclose(offset[:6, g], 2.0) and np.allclose(offset[6:, g], 0) and not add.any()
    add, offset, _ = m._scenario("oil_reverses", 12)
    assert abs(add[:, m.prim_cols.index("brent_crude_usd")].sum() + 35) < 1e-9
    base = m.aggregate_paths(m.simulate(12, n_paths=200, seed=3), "ALL")[:, -1]
    low = m.aggregate_paths(m.simulate(12, n_paths=200, seed=3, scenario="oil_reverses"), "ALL")[:, -1]
    assert np.median(low) < np.median(base)


def test_policy_events_hit_the_right_month_and_component(setup):
    cfg, s, macro = setup
    from model import load_policy_events
    m = ForecastModel(cfg).fit(s, macro)                     # origin 2026-04
    m.events = load_policy_events(cfg, ROOT)
    assert all(e["status"] == "enacted" and e["pct"] is not None for e in m.events)
    shocks = m.policy_shocks(6, pass_through=1.0)
    j = [c.label for c in m.components].index("diesel")
    assert abs(shocks[2, j] - 100 * np.log(1.031)) < 1e-9    # July 2026 = 3rd forecast month
    assert np.count_nonzero(shocks[[0, 1, 3, 4, 5]]) == 0
    assert not m.policy_shocks(6, pass_through=0.0).any()


def test_extra_drivers_respect_publication_lag(setup):
    cfg, _, macro = setup
    from model import primitives
    P = primitives(macro, cfg)
    for d in ("rain_anomaly", "overall_public_expenditure"):
        assert d in P.columns
    # fiscal enters two months late: the value at month t is the yoy3 rate of month t-2
    raw = macro["overall_public_expenditure"].rolling(3).sum()
    t = pd.Timestamp("2023-06-01")
    expect = 100 * np.log(raw.loc["2023-04-01"] / raw.loc["2022-04-01"])
    assert abs(P.loc[t, "overall_public_expenditure"] - expect) < 1e-9
