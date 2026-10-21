"""
settlement.py — resolve contracts from official releases (the market's oracle).

SETTLEMENT RULE (UBOS CIPI, monthly)
------------------------------------
A contract on series S for reference month M settles on the month-on-month
percentage change of S in M, computed from the *first release whose latest
month is M* (the "first print"), using that same release's values for M and
M-1. Because both levels come from one release, rebasing between releases
cannot move the result, and later revisions do not reopen a settled contract.
The change is rounded to `decimals` places, then bucketed with [lo, hi) edges.

Series are matched on the exact UBOS row label (as normalised by parse_cipi),
not the panel code: parse_cipi maps several labels to one code (e.g. rebar and
roofing sheets both become STEEL), which would make settlement ambiguous.

    load_releases(cfg)                          -> long frame of every parsed release
    first_print(releases, label, ref_month)     -> dict with value, levels, source file
    bucket(value, cuts)                         -> outcome index
    revision_report(releases)                   -> m/m change differences across vintages
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "ingest"))

from parse_cipi import parse_cipi_workbook, CipiParseError   # noqa: E402


def _ubos_cipi_files(raw_dirs: list[str]) -> list[Path]:
    seen, files = set(), []
    for d in raw_dirs:
        p = ROOT / d if not Path(d).is_absolute() else Path(d)
        for f in sorted(p.glob("*.xls*")):
            if "CIPI" not in f.name.upper() or f.name in seen or f.name.startswith("~$"):
                continue
            seen.add(f.name)
            files.append(f)
    return files


def load_releases(cfg: dict) -> pd.DataFrame:
    """Parse every release for the country into one long frame.
    Adds `release_month` = the latest month a release contains (its reference month)."""
    parser = cfg["settlement"]["parser"]
    if parser != "ubos_cipi":
        raise NotImplementedError(f"no settlement adapter for parser {parser!r} yet")
    frames = []
    for f in _ubos_cipi_files(cfg["settlement"]["raw_dirs"]):
        try:
            frames.append(parse_cipi_workbook(f))
        except CipiParseError:
            continue
    if not frames:
        raise FileNotFoundError("no parseable releases found in " + ", ".join(cfg["settlement"]["raw_dirs"]))
    rel = pd.concat(frames, ignore_index=True)
    rel = rel.drop_duplicates(["source_file", "series_label", "date"])
    rel["release_month"] = rel.groupby("source_file")["date"].transform("max")
    return rel


def series_history(releases: pd.DataFrame, label: str, as_of: pd.Timestamp | None = None) -> pd.Series:
    """Levels of one series from the newest release published up to `as_of` (inclusive,
    by reference month). One release = one consistent base, so no splicing is needed."""
    rel = releases[releases.series_label == label]
    if as_of is not None:
        rel = rel[rel.release_month <= as_of]
    if rel.empty:
        return pd.Series(dtype=float)
    newest = rel.loc[rel.release_month.idxmax(), "source_file"]
    s = rel[rel.source_file == newest].set_index("date")["index_value"].sort_index()
    return s.asfreq("MS")


def first_print(releases: pd.DataFrame, label: str, ref_month, decimals: int = 2) -> dict | None:
    """The settlement value for (label, ref_month), or None if not yet published."""
    ref = pd.Timestamp(ref_month).to_period("M").to_timestamp()
    prev = ref - pd.DateOffset(months=1)
    rel = releases[releases.series_label == label]
    first = rel[rel.release_month == ref]
    note = "first print"
    if first.empty:
        # Missed the release itself (e.g. file not harvested): fall back to the earliest
        # later release that contains the month, and say so in the settlement record.
        later = rel[(rel.release_month > ref) & (rel.date == ref)]
        if later.empty:
            return None
        first = rel[rel.release_month == later.release_month.min()]
        note = "first print not on file; settled on earliest later release"
    src = sorted(first.source_file.unique())[0]
    f = first[first.source_file == src].set_index("date")["index_value"]
    if ref not in f.index or prev not in f.index:
        return None
    level, prev_level = float(f[ref]), float(f[prev])
    value = round((level / prev_level - 1) * 100, decimals)
    return {"label": label, "ref_month": ref.strftime("%Y-%m"), "value": value,
            "level": level, "prev_level": prev_level, "source_file": src, "note": note}


def bucket(value: float, cuts: list[float]) -> int:
    """Outcome index for a settlement value; buckets are [lo, hi), outer ones open."""
    return int(np.searchsorted(np.asarray(cuts, dtype=float), value, side="right"))


def bucket_labels(cuts: list[float], unit: str = "%") -> list[str]:
    def f(x):
        return f"{x:+.2f}{unit}".replace("+0.00", "0.00")
    out = [f"below {f(cuts[0])}"]
    for lo, hi in zip(cuts, cuts[1:]):
        out.append("unchanged" if (lo == 0 and hi <= 0.01) else f"{f(lo)} to below {f(hi)}")
    out.append(f"{f(cuts[-1])} or more")
    return out


def revision_report(releases: pd.DataFrame) -> pd.DataFrame:
    """For every (series, month) printed by more than one release: the spread of its
    month-on-month % change across releases. Changes, not levels, so a rebasing
    between releases is not counted as a revision (settlement uses changes too)."""
    rel = releases.sort_values(["source_file", "series_label", "date"]).copy()
    prev = rel.groupby(["source_file", "series_label"])["index_value"].shift(1)
    prev_date = rel.groupby(["source_file", "series_label"])["date"].shift(1)
    consecutive = prev_date == rel["date"] - pd.DateOffset(months=1)
    rel["mom_pct"] = ((rel["index_value"] / prev - 1) * 100).where(consecutive)
    g = rel.dropna(subset=["mom_pct"]).groupby(["series_label", "date"])["mom_pct"]
    rep = pd.DataFrame({"n_vintages": g.size(), "min_pct": g.min(), "max_pct": g.max()})
    rep = rep[rep.n_vintages > 1]
    rep["spread_pp"] = rep["max_pct"] - rep["min_pct"]
    return rep.reset_index()
