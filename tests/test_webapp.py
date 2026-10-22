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
    import importlib
    import app as webapp
    importlib.reload(webapp)
    from fastapi.testclient import TestClient
    from ledger import Exchange
    c = TestClient(webapp.app)
    assert c.get("/admin?key=wrong").status_code == 403
    r = c.post("/admin/invite?key=k", data={"name": "Jane Okello", "org": "Okello Builders", "country": "uganda"},
               follow_redirects=False)
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
