"""
test_market.py
==============
Tests for the forecasting-market layer (src/market/). Run with:  pytest -q

They assert the properties the market's fairness rests on:
(a) the LMSR opens at the prior, charges path-independent costs and has bounded loss;
(b) settlement uses the first print and is immune to a rebasing in a later release;
(c) buckets are [lo, hi) and nowcast probabilities are floored and sum to one;
(d) the ledger refuses invalid trades, pays winners and refunds void markets.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC / "market"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lmsr import LMSR                                                       # noqa: E402
from ledger import Exchange, ExchangeError                                  # noqa: E402
from nowcast import predictive_probs, walk_forward, mom_changes             # noqa: E402
from settlement import load_releases, first_print, bucket, bucket_labels, series_history  # noqa: E402
from country import load_country, validate, CountryConfigError              # noqa: E402
from test_pipeline import _write                                            # noqa: E402


# ----------------------------------------------------------------- LMSR --
def test_lmsr_opens_at_prior_and_bounds_loss():
    prior = np.array([0.1, 0.2, 0.3, 0.4])
    mm = LMSR(prior, b=50)
    assert np.allclose(mm.prices(), prior)
    assert abs(mm.max_loss() - 50 * np.log(10)) < 1e-9


def test_lmsr_cost_is_path_independent():
    a, b = LMSR([0.25] * 4, 100), LMSR([0.25] * 4, 100)
    ca = a.trade(0, 10) + a.trade(1, 5) + a.trade(0, -3)
    cb = b.trade(0, 7) + b.trade(1, 5)
    assert abs(ca - cb) < 1e-9
    assert np.allclose(a.prices(), b.prices())


def test_lmsr_buying_raises_price():
    mm = LMSR([0.5, 0.5], 100)
    mm.trade(1, 30)
    assert mm.prices()[1] > 0.5


# ------------------------------------------------------------ settlement --
def test_buckets_are_half_open():
    cuts = [-1.0, 0.0, 0.01, 1.0]
    assert bucket(-1.0, cuts) == 1
    assert bucket(0.0, cuts) == 2          # exactly unchanged
    assert bucket(0.01, cuts) == 3
    assert bucket(1.0, cuts) == 4
    assert bucket(-5, cuts) == 0
    assert bucket_labels(cuts)[2] == "unchanged"


def _cfg(raw_dir):
    return {"settlement": {"parser": "ubos_cipi", "raw_dirs": [str(raw_dir)]}}


def test_first_print_ignores_later_rebasing(tmp_path):
    # Release for March: cement 100, 101, 102.01 (Jan-Mar 2026).
    _write(tmp_path / "CIPI_MAR_2026.xlsx", "Idx", ["Item", "2026M01", "2026M02", "2026M03"],
           [("Cement", [100, 101, 102.01])])
    # April release rebased x1.5 and revises March; the March contract must not move.
    _write(tmp_path / "CIPI_APR_2026.xlsx", "Idx", ["Item", "2026M02", "2026M03", "2026M04"],
           [("Cement", [151.5, 155.0, 158.1])])
    rel = load_releases(_cfg(tmp_path))
    label = rel.series_label.iloc[0]
    mar = first_print(rel, label, "2026-03")
    assert mar["value"] == 1.0 and mar["source_file"] == "CIPI_MAR_2026.xlsx"
    apr = first_print(rel, label, "2026-04")
    assert apr["value"] == 2.0 and apr["source_file"] == "CIPI_APR_2026.xlsx"
    assert first_print(rel, label, "2026-05") is None
    # history for the nowcast comes from one release only (no cross-base mixing)
    assert series_history(rel, label).iloc[-1] == 158.1


def test_first_print_falls_back_to_later_release(tmp_path):
    _write(tmp_path / "CIPI_APR_2026.xlsx", "Idx", ["Item", "2026M02", "2026M03", "2026M04"],
           [("Cement", [100, 102, 103])])
    rel = load_releases(_cfg(tmp_path))
    fp = first_print(rel, rel.series_label.iloc[0], "2026-03")
    assert fp["value"] == 2.0 and "earliest later release" in fp["note"]


# ------------------------------------------------------------- nowcast --
def _changes(n=96, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2018-01-01", periods=n, freq="MS")
    lv = 100 * np.exp(np.cumsum(rng.normal(0.002, 0.01, n)))
    lv[rng.random(n) < 0.3] = np.nan           # lumpy: hold some months flat
    lv = pd.Series(lv, idx).ffill().bfill()
    return mom_changes(lv)


def test_nowcast_probabilities_floored_and_normalised():
    r = _changes()
    cuts = [-1.0, 0.0, 0.01, 1.0]
    for h in (1, 3):
        p = predictive_probs(r, r.index[-1] + pd.DateOffset(months=h), cuts, horizon=h, floor=0.02)
        assert abs(p.sum() - 1) < 1e-9 and p.min() >= 0.02 - 1e-12 and len(p) == 5


def test_walk_forward_has_no_lookahead():
    r = _changes()
    s = walk_forward(r, [-1.0, 0.0, 0.01, 1.0], horizon=2, min_train=36)
    assert len(s) == len(r) - 37
    assert s.target.iloc[0] == r.index[37]


# --------------------------------------------------------------- ledger --
def _market(ex, closes="2099-01-01T00:00:00Z"):
    return ex.create_market("uganda", "CEM", "cement", "Cement", "2026-05", [-1.0, 0.0, 0.01, 1.0],
                            bucket_labels([-1.0, 0.0, 0.01, 1.0]), [0.1, 0.2, 0.2, 0.3, 0.2], 100,
                            closes, "2099-06-01T00:00:00Z")


def test_ledger_trade_and_settle_pays_winners():
    ex = Exchange(":memory:", starting_points=1000)
    mid = _market(ex)
    ex.open_account("a"); ex.open_account("b")
    ca = ex.trade("a", mid, 3, 50)
    cb = ex.trade("b", mid, 1, 50)
    assert ex.market(mid)["prices"][3] > 0.3
    with pytest.raises(ExchangeError):
        _market(ex)                                     # duplicate contract
    assert ex.settle(mid, 0.42, "test") == 3
    assert abs(ex.balance("a") - (1000 - ca + 50)) < 1e-9
    assert abs(ex.balance("b") - (1000 - cb)) < 1e-9
    with pytest.raises(ExchangeError):
        ex.trade("a", mid, 3, 1)                         # settled markets are closed


def test_ledger_rejects_bad_trades():
    ex = Exchange(":memory:", starting_points=10)
    mid = _market(ex)
    ex.open_account("a")
    with pytest.raises(ExchangeError):
        ex.trade("a", mid, 0, 1000)                      # cannot afford
    with pytest.raises(ExchangeError):
        ex.trade("a", mid, 0, -1)                        # cannot sell what you do not hold
    closed = ex.create_market("uganda", "SAND", "sand", "Sand", "2026-05", [0.0], ["down", "up"],
                              [0.5, 0.5], 100, "2026-01-01T00:00:00Z", "2026-06-01T00:00:00Z")
    with pytest.raises(ExchangeError):
        ex.trade("a", closed, 0, 1)                      # past close


def test_ledger_void_refunds():
    ex = Exchange(":memory:", starting_points=1000)
    mid = _market(ex)
    ex.open_account("a")
    ex.trade("a", mid, 2, 40); ex.trade("a", mid, 2, -10)
    ex.void(mid, "no release")
    assert abs(ex.balance("a") - 1000) < 1e-9


# --------------------------------------------------------------- config --
def test_country_configs_validate():
    ug = load_country("uganda")
    assert ug["markets"] and all(m["cuts"] == sorted(m["cuts"]) for m in ug["markets"])
    assert load_country("kenya")["status"] == "planned"


def test_config_refuses_real_money():
    cfg = load_country("uganda")
    cfg["regulation"]["mode"] = "licensed"
    with pytest.raises(CountryConfigError):
        validate(cfg, "uganda")


def test_structural_opener_probabilities():
    release = Path(__file__).resolve().parents[1] / "data" / "raw" / "06_2026CIPI_APRIL_2026_PIN_UPS.xlsx"
    if not release.exists():
        pytest.skip("April 2026 CIPI release not on disk")
    from structural import StructuralOpener
    op = StructuralOpener(release, n_paths=200).fit("2025-12-01")
    for label in ("overall construction index", "cement"):
        assert op.has(label)
        p = op.probs(label, "2026-02-01", [-1.0, 0.0, 0.01, 1.0], floor=0.02)
        assert abs(p.sum() - 1) < 1e-9 and p.min() >= 0.02 - 1e-12
    with pytest.raises(ValueError):
        op.probs("cement", "2025-12-01", [0.0])               # not after the origin
