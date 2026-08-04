#!/usr/bin/env python3
"""
pull_ubos_cipi.py
=================
Bulk-download UBOS index files (CIPI/CPI/PPI-Manufacturing) from UBOS pages.

This helper crawls the UBOS CIPI publications page and downloads all matching
release files into `data/raw/ubos_cipi_downloads/`, while writing a manifest.

Why this script exists:
- UBOS file naming changes over time.
- The page can contain PDFs and/or Excel tables depending on release practice.
- We need a reproducible harvest step with an auditable manifest.

Usage:
    python src/ingest/pull_ubos_cipi.py --out data/raw/ubos_cipi_downloads
"""

from __future__ import annotations

import argparse
import csv
import re
import ssl
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


UBOS_DATASETS_PAGE = "https://www.ubos.org/datasets/"
UBOS_CIPI_PUBLICATIONS_PAGE = "https://www.ubos.org/?pagename=explore-publications&p_id=104"


@dataclass
class Hit:
    url: str
    ext: str


def fetch_text(url: str) -> str:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (CiO-pipeline)"})
    with urlopen(req, timeout=60) as r:  # nosec B310 - controlled URL
        return r.read().decode("utf-8", errors="ignore")


def find_links(html: str, page_url: str, include_pattern: str, exts: tuple[str, ...]) -> list[Hit]:
    upload_dir = "statistics" if "datasets" in page_url else "publications"
    ext_pat = "|".join(exts)
    pat = re.compile(
        rf'href="(https://www\.ubos\.org/wp-content/uploads/{upload_dir}/[^"]+\.({ext_pat}))"',
        re.I,
    )
    raw_urls = sorted(set(m.group(1).strip() for m in pat.finditer(html)))
    urls = []
    include_re = re.compile(include_pattern, re.I)
    for u in raw_urls:
        if not include_re.search(u):
            continue
        urls.append(u)
    out = []
    for u in urls:
        ext = Path(urlparse(u).path).suffix.lower().lstrip(".")
        out.append(Hit(url=u, ext=ext))
    return out


def safe_name(url: str) -> str:
    name = Path(urlparse(url).path).name.strip()
    name = re.sub(r"\s+", "_", name)
    return name


def normalise_url(url: str) -> str:
    """Encode spaces and unsafe characters in path while preserving the domain."""
    p = urlparse(url)
    safe_path = quote(p.path, safe="/-_.~%")
    return f"{p.scheme}://{p.netloc}{safe_path}"


def download(url: str, dst: Path) -> tuple[str, int]:
    url_n = normalise_url(url)
    req = Request(url_n, headers={"User-Agent": "Mozilla/5.0 (CiO-pipeline)"})
    contexts = [None, ssl._create_unverified_context()]  # noqa: SLF001
    last_err = None
    for attempt in range(1, 4):
        for ctx in contexts:
            try:
                with urlopen(req, timeout=120, context=ctx) as r:  # nosec B310 - controlled URL
                    data = r.read()
                dst.write_bytes(data)
                return "ok", len(data)
            except Exception as e:  # noqa: BLE001
                last_err = e
        time.sleep(1.0 * attempt)
    return f"error: {last_err}", 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Download UBOS index files for CIPI/CPI/PPI workflows.")
    ap.add_argument("--out", default="data/raw/ubos_cipi_downloads")
    ap.add_argument("--manifest", default="data/raw/ubos_cipi_manifest.csv")
    ap.add_argument("--page-url", default=UBOS_DATASETS_PAGE,
                    help="UBOS page to crawl (datasets or publications page).")
    ap.add_argument(
        "--include-pattern",
        default=r"cipi|cpi|ppi|manufacturing|construction|csi",
        help="Case-insensitive regex used to keep only relevant links.",
    )
    ap.add_argument(
        "--formats",
        default="xlsx,xls",
        help="Comma-separated extensions to collect (e.g. xlsx,xls,pdf).",
    )
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    exts = tuple(e.strip().lower().lstrip(".") for e in args.formats.split(",") if e.strip())
    html = fetch_text(args.page_url)
    hits = find_links(html, args.page_url, args.include_pattern, exts)
    if not hits:
        raise SystemExit("No matching links found on UBOS page.")

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows: list[dict] = []
    for h in hits:
        fn = safe_name(h.url)
        dst = out_dir / fn
        status, nbytes = download(h.url, dst)
        rows.append(
            {
                "url": h.url,
                "filename": fn,
                "ext": h.ext,
                "status": status,
                "bytes": nbytes,
                "downloaded_utc": now,
            }
        )

    manifest = Path(args.manifest)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with manifest.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["url", "filename", "ext", "status", "bytes", "downloaded_utc"],
        )
        w.writeheader()
        w.writerows(rows)

    n_ok = sum(r["status"] == "ok" for r in rows)
    n_xlsx = sum(r["ext"] in {"xlsx", "xls"} for r in rows)
    n_pdf = sum(r["ext"] == "pdf" for r in rows)
    print(f"Harvested {len(rows)} links ({n_ok} downloaded).")
    print(f"By type: xls/xlsx={n_xlsx}, pdf={n_pdf}")
    print(f"Manifest: {manifest}")


if __name__ == "__main__":
    main()
