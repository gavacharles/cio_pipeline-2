"""
country.py — load and validate a country configuration for the forecasting market.

Each country is one YAML file under config/countries/. The market code reads
everything country-specific (settlement source, release rules, contract list)
from that file, so adding a country means writing a config and, if its
statistics office publishes in a new format, a settlement adapter.

    load_country("uganda")  -> dict (validated)
    list_countries()        -> ["kenya", "uganda", ...]
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
COUNTRY_DIR = ROOT / "config" / "countries"

REQUIRED = ("country", "iso3", "status", "currency", "regulation", "settlement", "exchange", "markets")
REQUIRED_SETTLEMENT = ("statistics_office", "parser", "raw_dirs", "frequency", "quantity",
                       "decimals", "void_after_days")
REQUIRED_MARKET = ("code", "label", "title", "cuts")


class CountryConfigError(ValueError):
    """Raised when a country file is missing fields or has malformed contracts."""


def list_countries() -> list[str]:
    return sorted(p.stem for p in COUNTRY_DIR.glob("*.yaml"))


def validate(cfg: dict, name: str = "?") -> dict:
    missing = [k for k in REQUIRED if k not in cfg]
    if missing:
        raise CountryConfigError(f"{name}: missing keys {missing}")
    missing = [k for k in REQUIRED_SETTLEMENT if k not in cfg["settlement"]]
    if missing:
        raise CountryConfigError(f"{name}: settlement missing {missing}")
    if cfg["regulation"].get("mode") != "play_money":
        # Deliberate tripwire: real-money modes need legal sign-off, not a config edit.
        raise CountryConfigError(f"{name}: regulation.mode must be play_money until a "
                                 "licence or sandbox approval is documented in docs/MARKET_DESIGN.md")
    codes = set()
    for m in cfg["markets"]:
        missing = [k for k in REQUIRED_MARKET if k not in m]
        if missing:
            raise CountryConfigError(f"{name}: market {m.get('code')} missing {missing}")
        cuts = [float(c) for c in m["cuts"]]
        if len(cuts) < 1 or any(b <= a for a, b in zip(cuts, cuts[1:])):
            raise CountryConfigError(f"{name}: market {m['code']} cuts must be strictly increasing")
        m.setdefault("opening", "pooled")
        if m["opening"] not in ("pooled", "structural", "blend"):
            raise CountryConfigError(f"{name}: market {m['code']} opening must be pooled, structural or blend")
        if m["code"] in codes:
            raise CountryConfigError(f"{name}: duplicate market code {m['code']}")
        codes.add(m["code"])
        m["cuts"] = cuts
    return cfg


def load_country(name: str) -> dict:
    path = COUNTRY_DIR / f"{name.lower()}.yaml"
    if not path.exists():
        raise CountryConfigError(f"no config for {name!r}; available: {list_countries()}")
    with open(path, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    cfg["key"] = path.stem
    return validate(cfg, path.stem)


def market_spec(cfg: dict, code: str) -> dict:
    for m in cfg["markets"]:
        if m["code"] == code:
            return m
    raise KeyError(f"{cfg['key']}: no market {code}")
