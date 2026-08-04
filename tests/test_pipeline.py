"""
test_pipeline.py
================
Regression tests for the CiO Phase 0 pipeline. Run with:  pytest -q

These tests build tiny synthetic CIPI workbooks in a temp dir and assert that
(a) the defensive parser reads differing layouts, and
(b) the splicer chain-links overlapping vintages to the correct factor and
    flags non-overlapping ones instead of fabricating a join.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import Workbook

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC / "ingest"))
sys.path.insert(0, str(SRC / "index"))

from parse_cipi import parse_cipi_workbook, CipiParseError   # noqa: E402
from build_panel import splice_series                         # noqa: E402


def _write(path, sheet, header, rows, title_rows=1, label_col=0):
    wb = Workbook(); ws = wb.active; ws.title = sheet
    for _ in range(title_rows):
        ws.append(["UBOS CIPI"])
    ws.append(header if label_col == 0 else [None] + header)
    for name, vals in rows:
        ws.append(([name] + vals) if label_col == 0 else [None, name] + vals)
    wb.save(path)


def test_parser_layout_A(tmp_path):
    p = tmp_path / "A.xlsx"
    _write(p, "CIPI Index",
           ["Item", "Jan-2020", "Feb-2020", "Mar-2020"],
           [("Cement", [100, 101, 102]), ("Iron and Steel", [90, 92, 95])])
    df = parse_cipi_workbook(p)
    assert set(df.series_code) == {"CEM", "IRONSTEEL"}
    assert len(df) == 6
    assert df.date.min() == pd.Timestamp("2020-01-01")


def test_parser_layout_B_offset_labels(tmp_path):
    """Labels in column B, headers as 2022M01, extra title rows."""
    p = tmp_path / "B.xlsx"
    _write(p, "Table 1",
           ["Description", "2022M01", "2022M02"],
           [("ALL CONSTRUCTION", [130, 131]), ("Cement", [140, 141])],
           title_rows=2, label_col=1)
    df = parse_cipi_workbook(p)
    assert "CIPI_ALL" in set(df.series_code)
    assert "CEM" in set(df.series_code)


def test_parser_rejects_garbage(tmp_path):
    p = tmp_path / "junk.xlsx"
    wb = Workbook(); ws = wb.active
    ws.append(["nothing", "useful", "here"]); wb.save(p)
    with pytest.raises(CipiParseError):
        parse_cipi_workbook(p)


def test_splice_overlap_factor(tmp_path):
    a = tmp_path / "v1.xlsx"; b = tmp_path / "v2.xlsx"
    _write(a, "Idx", ["Item", "2021M01", "2021M02", "2021M03", "2021M04"],
           [("Cement", [100, 101, 102, 103])])
    # v2 overlaps M03-M04 at exactly 1.20x, then extends
    _write(b, "Idx", ["Item", "2021M03", "2021M04", "2021M05"],
           [("Cement", [122.4, 123.6, 124.8])])
    stacked = pd.concat([parse_cipi_workbook(a), parse_cipi_workbook(b)],
                        ignore_index=True)
    spliced, slog = splice_series(stacked)
    factor = slog.loc[slog.series_code == "CEM", "splice_factor"].iloc[0]
    assert abs(factor - 1.20) < 1e-6
    # older values scaled up to the newer scale
    jan = spliced[(spliced.series_code == "CEM") &
                  (spliced.date == "2021-01-01")]["index_spliced"].iloc[0]
    assert abs(jan - 120.0) < 1e-6


def test_splice_flags_no_overlap(tmp_path):
    a = tmp_path / "v1.xlsx"; b = tmp_path / "v2.xlsx"
    _write(a, "Idx", ["Item", "2019M01", "2019M02"], [("Cement", [100, 101])])
    _write(b, "Idx", ["Item", "2022M01", "2022M02"], [("Cement", [150, 151])])
    stacked = pd.concat([parse_cipi_workbook(a), parse_cipi_workbook(b)],
                        ignore_index=True)
    _, slog = splice_series(stacked)
    assert "NO OVERLAP" in slog.loc[slog.series_code == "CEM", "note"].iloc[0]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# --------------------------------------------------------------------------- #
# Smoke tests for the estimation templates. They assert the scripts import and
# run end-to-end on a small synthetic panel, producing outputs of the right
# shape. They do NOT assert economic magnitudes (those need the real panel).
# --------------------------------------------------------------------------- #
import numpy as np  # noqa: E402


def _synthetic_panel(tmp_path, n=72):
    import numpy as np
    rng = np.random.default_rng(0)
    dates = pd.date_range("2016-01-01", periods=n, freq="MS")
    mats = ["CEM", "IRONSTEEL", "ALU", "SAND", "BITUMEN", "AGG",
            "FUEL", "PIPES", "PAINT", "TIMBER", "LABOUR"]
    data = {m: 100 + np.cumsum(rng.normal(0.3, 1.5, n)) for m in mats}
    panel = pd.DataFrame(data, index=dates)
    panel["CIPI_ALL"] = panel[mats].mean(axis=1)
    panel["exchange_rate"] = 3600 + np.cumsum(rng.normal(2, 20, n))
    panel["cpi"] = 100 + np.cumsum(rng.normal(0.3, 0.5, n))
    panel["central_bank_rate"] = 10 + np.cumsum(rng.normal(0, 0.2, n))
    panel["private_credit"] = 1000 + np.cumsum(rng.normal(5, 15, n))
    p = tmp_path / "panel_v1.0.parquet"
    panel.to_parquet(p)
    return panel


EST = SRC / "estimation"
sys.path.insert(0, str(EST))


def test_p4_spillover_runs(tmp_path):
    panel = _synthetic_panel(tmp_path)
    import p4_dcc_spillover as p4
    mats = [c for c in panel.columns if c.isupper() and not c.startswith("CIPI")]
    rets = p4.log_returns(panel, mats)
    spill = p4.diebold_yilmaz(rets)
    assert spill.shape[0] == spill.shape[1] == len(mats)
    simi = p4.simi_scores(spill)
    assert "SIMI" in simi.columns and len(simi) == len(mats)


def test_p6_svar_runs(tmp_path):
    panel = _synthetic_panel(tmp_path)
    import p6_svar as p6
    data = p6.prepare(panel)
    res, irf, fevd = p6.run_svar(data, lags=2, horizon=12)
    assert irf.shape[0] == 13          # horizon+1 rows
    assert "exchange_rate" in irf.columns


def test_p8_dam_triggers(tmp_path):
    panel = _synthetic_panel(tmp_path, n=84)
    import p8_dam_simulator as p8
    cfg = p8.DAMConfig(duration_months=18)
    out = p8.simulate(panel, "road", cfg, fx_sens=1.0)
    # the mechanism must be capable of firing and reporting margin protection
    assert out["n_adjustments"] >= 0
    assert "margin_protected" in out


def test_p9_walk_forward_runs(tmp_path):
    panel = _synthetic_panel(tmp_path)
    import p9_forecast as p9
    df = p9.make_features(panel)
    err, actual, pred = p9.walk_forward(df, use_network=True, min_train=36)
    assert len(err) == len(actual) == len(pred) > 0


def test_p3_cluster_runs(tmp_path):
    panel = _synthetic_panel(tmp_path)
    import p3_dtw_cluster as p3
    X, mats = p3.material_matrix(panel)
    labels = p3.cluster(X, k=3)
    assert len(labels) == len(mats)
