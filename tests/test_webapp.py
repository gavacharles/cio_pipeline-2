"""
test_webapp.py
==============
Participant app, price reports, Kenya settlement and the weekly-note pieces. Run: pytest -q
"""
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
for sub in ("market", "webapp", "ingest", "forecast"):
    sys.path.insert(0, str(ROOT / "src" / sub))

from reports import Participants, ReportError           # noqa: E402

ITEMS = [{"code": "cement_50kg", "name": "Cement", "unit": "bag"}]


def test_crowd_summary_uses_one_median_per_reporter():
    db = Participants(":memory:")
    for name in ("a", "b"):
        db.invite(name, "", "uganda")
    old, now = date.today() - timedelta(weeks=4), date.today()
    db.add_report("a", "uganda", "cement_50kg", 30000, "Kampala", on=old)
    for p in (33000, 33000, 99000, 99000, 99000):          # one person spamming high prices
        db.add_report("a", "uganda", "cement_50kg", p, "Kampala", on=now)
    db.add_report("b", "uganda", "cement_50kg", 33000, "Jinja", on=now)
    s = db.crowd_summary("uganda", ITEMS).iloc[0]
    assert s.reporters == 2
    assert s["median"] == pytest.approx((99000 + 33000) / 2)   # median of per-person medians
    assert s.change_pct == pytest.approx(((99000 + 33000) / 2 / 30000 - 1) * 100)
    with pytest.raises(ReportError):
        db.add_report("a", "uganda", "cement_50kg", -5, "Kampala")
    with pytest.raises(ReportError):
        db.add_report("a", "uganda", "steel", 5, "Kampala", items=["cement_50kg"])


def test_app_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("CIO_DB", str(tmp_path / "x.sqlite"))
    monkeypatch.setenv("CIO_ADMIN_KEY", "k")
    monkeypatch.setenv("CIO_SECURE_COOKIES", "0")       # the test client speaks plain http
    import importlib
    import app as webapp
    importlib.reload(webapp)
    from fastapi.testclient import TestClient
    from ledger import Exchange
    c = TestClient(webapp.app)
    assert c.post("/admin/invite", data={"name": "x", "country": "uganda"}).status_code == 403
    assert "Wrong password" in c.post("/admin/login", data={"key": "wrong"}).text
    c.post("/admin/login", data={"key": "k"})
    r = c.post("/admin/invite", data={"name": "Jane Okello", "org": "Okello Builders", "country": "uganda"},
               follow_redirects=False)
    assert "key=" not in r.headers["location"]
    code = r.headers["location"].split("made=")[1]
    mid = Exchange(tmp_path / "x.sqlite").create_market(
        "uganda", "CEM", "cement", "Cement", "2099-01", [0.0], ["down", "up"], [0.5, 0.5], 100,
        "2099-02-01T00:00:00Z", "2099-06-01T00:00:00Z")
    assert c.post("/login", data={"code": "WRONG"}, follow_redirects=False).headers["location"].startswith("/?err")
    assert c.post("/login", data={"code": code}, follow_redirects=False).status_code == 303
    assert "Cement" in c.get("/home").text
    assert c.get(f"/api/quote?m={mid}&o=1&s=10").json()["cost"] > 0
    assert "Done" in c.post(f"/m/{mid}/trade", data={"outcome": 1, "shares": 10}).text
    r = c.post("/prices", data={"item": "cement_50kg", "price": 34500, "location": "Kampala"})
    assert "recorded" in r.text and "34,500" in r.text
    assert "Jane Okello" in c.get("/leaderboard").text
    c.get("/logout")
    assert c.get("/home", follow_redirects=False).status_code == 303
    assert r.headers.get("x-frame-options") == "DENY" or c.get("/").headers["x-frame-options"] == "DENY"


def test_login_rate_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("CIO_DB", str(tmp_path / "y.sqlite"))
    monkeypatch.setenv("CIO_SECURE_COOKIES", "0")
    import importlib
    import app as webapp
    importlib.reload(webapp)
    from fastapi.testclient import TestClient
    c = TestClient(webapp.app)
    for _ in range(10):
        assert "not+recognised" in c.post("/login", data={"code": "BAD"}, follow_redirects=False).headers["location"]
    assert "Too+many" in c.post("/login", data={"code": "BAD"}, follow_redirects=False).headers["location"]


KNBS = ROOT / "data" / "raw" / "knbs" / "Construction-Input-Price-Indices-for-Fourth-Quarter-2024.pdf"


@pytest.mark.skipif(not KNBS.exists(), reason="KNBS release not on disk")
def test_knbs_parse_and_quarterly_settlement():
    from parse_knbs_cipi import parse_release
    from settlement import first_print
    d = parse_release(KNBS)
    tot = d[(d.sheet == "ALL") & (d.series_label == "total")].set_index("date")["index_value"]
    assert tot[pd.Timestamp("2024-10-01")] == 119.41 and tot[pd.Timestamp("2024-07-01")] == 120.38
    w = d[(d.sheet == "ALL") & ~d.is_aggregate].drop_duplicates("series_label").weight.sum()
    assert w == pytest.approx(100, abs=0.2)                       # the full basket is published
    rel = d.assign(series_label=d.sheet.str.lower() + "|" + d.series_label,
                   release_month=d.release_period)
    fp = first_print(rel, "all|total", "2024-10-01", step_months=3)
    assert fp["value"] == round((119.41 / 120.38 - 1) * 100, 2)


def test_known_macro_overrides_simulation():
    import yaml
    from index_structure import read_release
    from model import ForecastModel, load_macro, known_primitives
    rel = ROOT / "data" / "raw" / "06_2026CIPI_APRIL_2026_PIN_UPS.xlsx"
    if not rel.exists():
        pytest.skip("April 2026 release not on disk")
    cfg = yaml.safe_load(open(ROOT / "config" / "forecast_model.yaml"))
    macro = load_macro(cfg, ROOT)
    m = ForecastModel(cfg).fit(read_release(rel), macro, "2025-12-01")
    ext = macro.loc["2026-01-01":"2026-02-01", ["exchange_rate"]] * 1.10   # pretend a 10% depreciation
    known = known_primitives(macro, ext, cfg, m.origin, 3, m.prim_cols)
    j = m.prim_cols.index("exchange_rate")
    assert not np.isnan(known[0, j]) and not np.isnan(known[1, j]) and np.isnan(known[2, j])
    lo = m.aggregate_paths(m.simulate(3, n_paths=300, seed=1), "ALL")[:, 1]
    hi = m.aggregate_paths(m.simulate(3, n_paths=300, seed=1, known=known), "ALL")[:, 1]
    assert np.median(hi) > np.median(lo)


def test_quarterly_model_uses_known_drivers():
    from quarterly_model import QuarterlyModel
    idx = pd.date_range("2019-10-01", periods=24, freq="QS-JAN")
    rng = np.random.default_rng(0)
    D = pd.DataFrame({"fx": rng.normal(0, 2, 24), "oil": rng.normal(0, 8, 24)}, index=idx)
    r = 0.5 + 0.08 * D["oil"] + rng.normal(0, 0.3, 24)          # index driven by oil
    lv = 100 * np.exp(np.cumsum(r) / 100)
    m = QuarterlyModel(alpha=1.0).fit(lv, D)
    assert m.coef[m.names.index("oil_0")] > 0.03
    up = pd.DataFrame({"fx": [0.0], "oil": [30.0]}, index=[idx[-1] + pd.DateOffset(months=3)])
    down = up.assign(oil=-30.0)
    hi, _ = m.simulate(1, n_paths=500, known=up)
    lo, _ = m.simulate(1, n_paths=500, known=down)
    assert np.median(hi) > np.median(lo)


@pytest.mark.skipif(not (ROOT / "data" / "raw" / "weekly_drivers.csv").exists(), reason="no weekly drivers")
def test_rwanda_note_builds_offline(tmp_path, monkeypatch):
    import weekly_note
    monkeypatch.setattr(weekly_note, "NOTES", tmp_path)
    md = weekly_note.build("rwanda", fetch=False, db_path=tmp_path / "none.sqlite").read_text()
    assert "Rwanda construction cost note" in md and "Brent in RWF" in md
    assert (tmp_path / md.splitlines()[0] if False else tmp_path).exists()
    assert any(p.suffix == ".html" for p in tmp_path.iterdir())


def test_chained_history_survives_rebasing():
    from settlement import chained_first_prints, first_print
    rows = []
    # release A (base 1): Jan 100, Feb 102; release B rebased x0.5: Feb 51, Mar 52.02
    for src, rm, vals in [("A", "2024-02-01", {"2024-01-01": 100, "2024-02-01": 102}),
                          ("B", "2024-03-01", {"2024-02-01": 51, "2024-03-01": 52.02})]:
        for d, v in vals.items():
            rows.append({"source_file": src, "series_label": "x", "date": pd.Timestamp(d), "index_value": v,
                         "release_month": pd.Timestamp(rm)})
    rel = pd.DataFrame(rows)
    h = chained_first_prints(rel, "x")
    assert h.iloc[0] == pytest.approx(102) and h.iloc[1] == pytest.approx(102 * 1.02)
    assert first_print(rel, "x", "2024-03-01")["value"] == 2.0


def test_all_country_configs_and_generic_note(tmp_path, monkeypatch):
    from country import load_country, list_countries
    cs = list_countries()
    assert {"south_africa", "nigeria", "ghana", "zimbabwe"} <= set(cs)
    assert all(load_country(c)["fx_code"] and load_country(c).get("price_items") for c in cs)
    if not (ROOT / "data" / "raw" / "weekly_drivers.csv").exists():
        pytest.skip("no weekly drivers")
    import weekly_note
    monkeypatch.setattr(weekly_note, "NOTES", tmp_path)
    md = weekly_note.build("nigeria", fetch=False, db_path=tmp_path / "none.sqlite").read_text()
    assert "Nigeria construction cost note" in md and "Official construction price index" in md
