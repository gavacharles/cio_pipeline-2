"""
build_panel.py
==============
Assemble panel_v1.0: stack all parsed CIPI vintages, splice across rebasings
into continuous series, join the macro block, run coverage diagnostics, and
write the versioned analytical panel that every paper (P1, P3-P6, P8, P9)
consumes.

PIPELINE
--------
  1. Parse every CIPI workbook in data/raw/ with parse_cipi.
  2. Stack into one long frame; detect overlapping vintages per series.
  3. Splice vintages by overlap-ratio linking (chain-linking), so a rebased
     series continues the level of the older one. Every splice factor is logged
     to data/processed/splice_log.csv for full auditability (P1's methodology
     requires this).
  4. Pivot to a wide material-by-month matrix; attach the macro block.
  5. Emit coverage/missingness diagnostics and a data dictionary.
  6. Write parquet + csv, stamped panel_version.

This module is deliberately conservative: where two vintages disagree on an
overlap, it records the discrepancy rather than silently averaging, and where a
series has no overlap to splice on, it keeps the segments separate and flags a
break so the analyst decides.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "ingest"))
from parse_cipi import parse_cipi_workbook, CipiParseError

log = logging.getLogger("build_panel")

PANEL_VERSION = "1.0"


# --------------------------------------------------------------------------- #
# 1-2. Parse + stack
# --------------------------------------------------------------------------- #
def parse_all_cipi(raw_dir: Path) -> pd.DataFrame:
    frames, failures = [], []
    books_all = sorted(raw_dir.rglob("*.xls*"))

    def _is_cipi_book(p: Path) -> bool:
        parts = [x.lower() for x in p.parts]
        if any(x in {"mofped_bulk", "macro_manual"} for x in parts):
            return False
        if "macro" in p.name.lower():
            return False
        if "cipi" not in p.name.lower():
            return False
        return True

    # De-duplicate by filename in case the same workbook exists in multiple
    # raw locations; prefer files from ubos_cipi_downloads when present.
    preferred: dict[str, Path] = {}
    for p in books_all:
        if not _is_cipi_book(p):
            continue
        key = p.name
        cur = preferred.get(key)
        if cur is None:
            preferred[key] = p
        else:
            cur_score = int("ubos_cipi_downloads" in cur.as_posix())
            new_score = int("ubos_cipi_downloads" in p.as_posix())
            if new_score > cur_score:
                preferred[key] = p

    books = sorted(preferred.values())
    for wb in books:
        try:
            frames.append(parse_cipi_workbook(wb))
        except (CipiParseError, Exception) as e:  # noqa: BLE001
            failures.append((wb.name, str(e)))
            log.error("FAILED %s: %s", wb.name, e)
    if not frames:
        raise RuntimeError("No CIPI workbooks parsed. Is data/raw/ populated?")
    stacked = pd.concat(frames, ignore_index=True)
    fail_path = raw_dir.parent / "processed" / "parse_failures.csv"
    if failures:
        pd.DataFrame(failures, columns=["file", "error"]).to_csv(
            fail_path, index=False)
    elif fail_path.exists():
        fail_path.unlink()
    log.info("Parsed %d workbooks (%d failed); %d raw observations.",
             len(frames), len(failures), len(stacked))
    return stacked


# --------------------------------------------------------------------------- #
# 3. Splice rebasing vintages
# --------------------------------------------------------------------------- #
def splice_series(stacked: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    For each series_code, chain-link its vintages (identified by source_file)
    onto a single continuous scale, anchored on the most recent vintage's base.
    Returns (spliced_long, splice_log).
    """
    out_rows, log_rows = [], []
    for code, g in stacked.groupby("series_code"):
        vintages = (g.groupby("source_file")["date"]
                      .agg(["min", "max"]).sort_values("max"))
        order = list(vintages.index)            # oldest -> newest
        # newest vintage is the reference scale (factor 1.0)
        cumulative = {order[-1]: 1.0}
        for older, newer in zip(order[:-1][::-1], order[1:][::-1]):
            a = g[g.source_file == older].set_index("date")["index_value"]
            b = g[g.source_file == newer].set_index("date")["index_value"]
            overlap = a.index.intersection(b.index)
            if len(overlap):
                ratio = float((b.loc[overlap] / a.loc[overlap]).median())
                note = f"overlap={len(overlap)}"
            else:
                ratio = np.nan
                note = "NO OVERLAP - segment kept separate, break flagged"
            cumulative[older] = cumulative.get(newer, 1.0) * ratio
            log_rows.append({"series_code": code, "older": older, "newer": newer,
                             "splice_factor": ratio, "note": note})
        for src, fac in cumulative.items():
            seg = g[g.source_file == src].copy()
            if np.isnan(fac):
                seg["index_spliced"] = np.nan
                seg["spliced"] = False
            else:
                seg["index_spliced"] = seg["index_value"] * fac
                seg["spliced"] = True
            out_rows.append(seg)
    spliced = pd.concat(out_rows, ignore_index=True)
    # When multiple vintages cover the same month, prefer the newest.
    spliced["vintage_rank"] = spliced.groupby(
        ["series_code", "date"])["source_file"].transform(
        lambda s: s.rank(method="dense", ascending=False))
    spliced = spliced.sort_values(["series_code", "date", "vintage_rank"])
    deduped = spliced.drop_duplicates(["series_code", "date"], keep="first")
    return deduped, pd.DataFrame(log_rows)


# --------------------------------------------------------------------------- #
# 4. Pivot + attach macro
# --------------------------------------------------------------------------- #
def to_wide(spliced: pd.DataFrame) -> pd.DataFrame:
    wide = spliced.pivot_table(index="date", columns="series_code",
                               values="index_spliced", aggfunc="first")
    return wide.sort_index()


def load_macro(raw_dir: Path) -> pd.DataFrame | None:
    pq = raw_dir / "macro_block.parquet"
    csv = raw_dir / "macro_block.csv"
    src = pq if pq.exists() else (csv if csv.exists() else None)
    if src is None:
        log.warning("No macro block found (run pull_ugatsdb.R). "
                    "Panel will contain CIPI only.")
        return None
    m = pd.read_parquet(src) if src.suffix == ".parquet" else pd.read_csv(src)
    date_col = next((c for c in m.columns if c.lower() in ("date", "period")), None)
    val_col = next((c for c in m.columns if c.lower() in ("value", "obs", "val")), None)
    if not date_col or "var" not in m.columns or not val_col:
        log.warning("Macro block schema unexpected; skipping join.")
        return None
    m[date_col] = pd.to_datetime(m[date_col]).dt.to_period("M").dt.to_timestamp()
    macro_wide = m.pivot_table(index=date_col, columns="var",
                               values=val_col, aggfunc="mean").sort_index()
    macro_wide = macro_wide.resample("MS").mean().ffill(limit=2)  # QGDP -> monthly
    return macro_wide


# --------------------------------------------------------------------------- #
# 5. Diagnostics
# --------------------------------------------------------------------------- #
def diagnostics(wide: pd.DataFrame, out_dir: Path) -> dict:
    cov = pd.DataFrame({
        "first_obs": wide.apply(lambda s: s.first_valid_index()),
        "last_obs": wide.apply(lambda s: s.last_valid_index()),
        "n_obs": wide.notna().sum(),
        "pct_missing": (wide.isna().mean() * 100).round(1),
    })
    cov.to_csv(out_dir / "coverage_report.csv")
    summary = {
        "panel_version": PANEL_VERSION,
        "built_utc": datetime.utcnow().isoformat(timespec="seconds"),
        "n_series": int(wide.shape[1]),
        "date_min": str(wide.index.min().date()) if len(wide) else None,
        "date_max": str(wide.index.max().date()) if len(wide) else None,
        "n_months": int(wide.shape[0]),
        "overall_pct_missing": float((wide.isna().mean().mean() * 100).round(2)),
    }
    (out_dir / "panel_manifest.json").write_text(json.dumps(summary, indent=2))
    return summary


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def build(raw_dir="data/raw", out_dir="data/processed") -> dict:
    raw_dir, out_dir = Path(raw_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    stacked = parse_all_cipi(raw_dir)
    spliced, splice_log = splice_series(stacked)
    splice_log.to_csv(out_dir / "splice_log.csv", index=False)

    cipi_wide = to_wide(spliced)
    macro = load_macro(raw_dir)
    panel = cipi_wide.join(macro, how="left") if macro is not None else cipi_wide

    panel.to_parquet(out_dir / f"panel_v{PANEL_VERSION}.parquet")
    panel.to_csv(out_dir / f"panel_v{PANEL_VERSION}.csv")
    summary = diagnostics(panel, out_dir)
    log.info("panel_v%s written: %d series x %d months (%.1f%% missing).",
             PANEL_VERSION, summary["n_series"], summary["n_months"],
             summary["overall_pct_missing"])
    return summary


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="Build panel_v1.0 from raw CIPI + macro.")
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--out", default="data/processed")
    args = ap.parse_args()
    s = build(args.raw, args.out)
    print(json.dumps(s, indent=2))
