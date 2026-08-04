#!/usr/bin/env python3
"""
pull_global_catalog.py
======================
Build a 2015-2026 multi-source macro pull from configured sources and write:
- data/raw/global_series_registry.csv   (quoted source/dataset/series + status)
- data/raw/global_macro_block.csv       (long format date,var,value,source,...)

This script starts from code-first ingestion. Sources that cannot be accessed
programmatically are still registered with explicit status and notes.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

import pandas as pd


@dataclass
class PullResult:
    frame: pd.DataFrame
    status: str
    message: str


def _get_json(url: str, timeout: int = 60) -> Any:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (cio-pipeline)"})
    with urlopen(req, timeout=timeout) as r:  # nosec B310
        return json.loads(r.read().decode("utf-8"))


def pull_world_bank(country: str, series: str, start_year: int, end_year: int) -> PullResult:
    url = (
        f"https://api.worldbank.org/v2/country/{quote(country)}/indicator/{quote(series)}"
        f"?format=json&per_page=2000&date={start_year}:{end_year}"
    )
    try:
        payload = _get_json(url)
        if not isinstance(payload, list) or len(payload) < 2 or payload[1] is None:
            return PullResult(pd.DataFrame(), "failed", "unexpected World Bank payload")
        rows = []
        for row in payload[1]:
            yr = row.get("date")
            val = row.get("value")
            if yr is None or val is None:
                continue
            rows.append({"date": pd.Timestamp(int(yr), 1, 1), "value": float(val)})
        if not rows:
            return PullResult(pd.DataFrame(), "empty", "no observations")
        return PullResult(pd.DataFrame(rows), "ok", f"{len(rows)} rows")
    except Exception as e:  # noqa: BLE001
        return PullResult(pd.DataFrame(), "failed", str(e))


def pull_imf_weo(country: str, series: str, start_year: int, end_year: int) -> PullResult:
    # IMF DataMapper API
    url = f"https://www.imf.org/external/datamapper/api/v1/{quote(series)}/{quote(country)}"
    try:
        payload = _get_json(url)
        values = payload.get("values", {}).get(series, {}).get(country, {})
        rows = []
        for k, v in values.items():
            try:
                yr = int(k)
            except Exception:
                continue
            if yr < start_year or yr > end_year or v is None:
                continue
            rows.append({"date": pd.Timestamp(yr, 1, 1), "value": float(v)})
        if not rows:
            return PullResult(pd.DataFrame(), "empty", "no observations")
        return PullResult(pd.DataFrame(rows), "ok", f"{len(rows)} rows")
    except Exception as e:  # noqa: BLE001
        return PullResult(pd.DataFrame(), "failed", str(e))


def pull_ugatsdb_csv(raw_dir: Path) -> PullResult:
    csv_path = raw_dir / "macro_block.csv"
    if not csv_path.exists():
        return PullResult(pd.DataFrame(), "empty", "macro_block.csv not found")
    try:
        df = pd.read_csv(csv_path)
        if df.empty:
            return PullResult(pd.DataFrame(), "empty", "macro_block.csv empty")

        date_col = next((c for c in df.columns if c.lower() in {"date", "period"}), None)
        val_col = next((c for c in df.columns if c.lower() in {"value", "obs", "val"}), None)
        if date_col is None or val_col is None or "var" not in df.columns:
            return PullResult(pd.DataFrame(), "failed", "macro_block schema unexpected")

        out = pd.DataFrame(
            {
                "date": pd.to_datetime(df[date_col], errors="coerce").dt.to_period("M").dt.to_timestamp(),
                "var": df["var"].astype(str),
                "value": pd.to_numeric(df[val_col], errors="coerce"),
            }
        ).dropna(subset=["date", "value"])
        return PullResult(out, "ok", f"{len(out)} rows")
    except Exception as e:  # noqa: BLE001
        return PullResult(pd.DataFrame(), "failed", str(e))


def main() -> None:
    ap = argparse.ArgumentParser(description="Pull and register multi-source series (2015-2026).")
    ap.add_argument("--config", default="config/global_series_2015_2026.json")
    ap.add_argument("--raw-dir", default="data/raw")
    ap.add_argument("--out-registry", default="data/raw/global_series_registry.csv")
    ap.add_argument("--out-block", default="data/raw/global_macro_block.csv")
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    start_year = int(cfg["window"]["start_year"])
    end_year = int(cfg["window"]["end_year"])
    country = cfg["window"]["country_iso3"]

    registry_rows = []
    block_rows = []

    ug_cache = None
    for item in cfg["sources"]:
        provider = item["provider"]
        source = item["source"]
        dataset = item["dataset"]
        series = item["series"]
        var = item["var"]
        freq = item["frequency"]
        notes = item.get("notes", "")

        if provider == "world_bank":
            res = pull_world_bank(country, series, start_year, end_year)
        elif provider == "imf_weo":
            res = pull_imf_weo(country, series, start_year, end_year)
        elif provider == "ugatsdb":
            if ug_cache is None:
                ug_cache = pull_ugatsdb_csv(Path(args.raw_dir))
            if ug_cache.status == "ok":
                d = ug_cache.frame[ug_cache.frame["var"] == var.replace("_ugx_usd", "").replace("_headline", "")]
                if d.empty:
                    # fallback mapping by known aliases
                    alias_map = {
                        "exchange_rate_ugx_usd": "exchange_rate",
                        "cpi_headline": "cpi",
                        "private_sector_credit": "private_credit",
                    }
                    d = ug_cache.frame[ug_cache.frame["var"] == alias_map.get(var, var)]
                if d.empty:
                    res = PullResult(pd.DataFrame(), "empty", "series absent in macro_block.csv")
                else:
                    res = PullResult(d[["date", "value"]].copy(), "ok", f"{len(d)} rows")
            else:
                res = ug_cache
        else:
            res = PullResult(pd.DataFrame(), "manual", "manual-only source; series quoted in registry")

        registry_rows.append(
            {
                "source": source,
                "provider": provider,
                "dataset": dataset,
                "series": series,
                "var": var,
                "frequency": freq,
                "start_year": start_year,
                "end_year": end_year,
                "status": res.status,
                "message": res.message,
                "notes": notes,
                "updated_utc": datetime.utcnow().isoformat(timespec="seconds"),
            }
        )

        if not res.frame.empty and res.status == "ok":
            tmp = res.frame.copy()
            tmp["source"] = source
            tmp["provider"] = provider
            tmp["dataset"] = dataset
            tmp["series"] = series
            tmp["var"] = var
            block_rows.append(tmp[["date", "var", "value", "source", "provider", "dataset", "series"]])

    reg = pd.DataFrame(registry_rows)
    reg_path = Path(args.out_registry)
    reg_path.parent.mkdir(parents=True, exist_ok=True)
    reg.to_csv(reg_path, index=False)

    block = pd.concat(block_rows, ignore_index=True) if block_rows else pd.DataFrame(
        columns=["date", "var", "value", "source", "provider", "dataset", "series"]
    )
    block = block.sort_values(["var", "date"]) if not block.empty else block
    blk_path = Path(args.out_block)
    blk_path.parent.mkdir(parents=True, exist_ok=True)
    block.to_csv(blk_path, index=False)

    print(f"registry: {reg_path} ({len(reg)} rows)")
    print(f"block   : {blk_path} ({len(block)} rows)")


if __name__ == "__main__":
    main()
