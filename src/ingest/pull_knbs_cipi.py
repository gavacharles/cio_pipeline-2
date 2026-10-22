#!/usr/bin/env python3
"""
pull_knbs_cipi.py — harvest Kenya's quarterly Construction Input Price Index releases.

KNBS publishes the CIPI quarterly as a PDF (base Dec 2019 = 100; prices referenced to
the 15th of the quarter's middle month). Each release carries six quarters of every
product index plus the published weights. This script finds every release PDF linked
from the KNBS CIPI page and downloads the ones not yet on disk.

Output: data/raw/knbs/*.pdf and data/raw/knbs/manifest.csv

    python src/ingest/pull_knbs_cipi.py [--out data/raw/knbs]
"""
from __future__ import annotations

import argparse
import csv
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
INDEX_PAGES = [
    "https://www.knbs.or.ke/button/construction-input-pi/",
    "https://www.knbs.or.ke/statistical-releases/",
]
PDF_RE = re.compile(r'https://www\.knbs\.or\.ke/wp-content/uploads/[^"\']*Construction[^"\']*\.pdf', re.I)
UA = {"User-Agent": "Mozilla/5.0 (CiO Lab data pipeline)"}


def fetch(url: str, timeout: int = 90) -> bytes:
    with urlopen(Request(url, headers=UA), timeout=timeout) as r:  # nosec B310 - fixed KNBS host
        return r.read()


def find_release_links() -> list[str]:
    links = set()
    for page in INDEX_PAGES:
        try:
            links |= set(PDF_RE.findall(fetch(page).decode("utf-8", "ignore")))
        except Exception as e:  # one page down should not stop the harvest
            print(f"  could not read {page}: {e}")
    return sorted(links)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "data" / "raw" / "knbs"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest = out / "manifest.csv"
    rows = {r["filename"]: r for r in csv.DictReader(open(manifest))} if manifest.exists() else {}
    new = 0
    for url in find_release_links():
        name = url.rsplit("/", 1)[-1]
        if (out / name).exists():
            continue
        try:
            data = fetch(url)
            (out / name).write_bytes(data)
            status, size = "ok", len(data)
            new += 1
        except Exception as e:
            status, size = f"error: {e}", 0
        rows[name] = {"url": url, "filename": name, "status": status, "bytes": size,
                      "downloaded_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    with open(manifest, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["url", "filename", "status", "bytes", "downloaded_utc"])
        w.writeheader()
        w.writerows(sorted(rows.values(), key=lambda r: r["filename"]))
    print(f"{new} new release(s); {sum(1 for p in out.glob('*.pdf'))} PDFs in {out}")


if __name__ == "__main__":
    main()
