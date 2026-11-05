"""Radar data for the precipitation events of the event catalog, from the command line.

The catalog (dataset/meta/radar_events.csv) lists the top snow, rain and mixed-precipitation
storms of 2023-10 → 2026-04 with their UTC start / end; it is built by
`analysis.radar_utils.build_event_catalog` from ASOS present-weather codes and GHCN daily
totals, and tutorials/radar.ipynb reads it. This script fills the radar caches for its
events (or for any day), and can rebuild a catalog from a dataset's own sensors.

Usage::

    python src/fetch_data/radar_events.py list                       # the catalog events
    python src/fetch_data/radar_events.py fetch mrms                 # MRMS for every event
    python src/fetch_data/radar_events.py fetch kokx --event 2024-03-23_rain
    python src/fetch_data/radar_events.py fetch mrms --day 2024-01-19        # any UTC day
    python src/fetch_data/radar_events.py select --dataset v2        # rebuild a catalog

MRMS lands in dataset/raw/radar/mrms/cache/ (src/fetch_data/mrms), KOKX samples in
dataset/raw/radar/nexrad/<dataset>/ (src/fetch_data/nexrad). `select` writes
dataset/raw/radar/radar_events_<dataset>.csv unless `--outfile` is given, so the
repository's catalog is not replaced by accident.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional, Sequence

# Add src to path so imports work when run as script
_src = Path(__file__).resolve().parents[2] / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

import pandas as pd

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = REPO_ROOT / "dataset"
EVENTS_CSV = DATASET_DIR / "meta" / "radar_events.csv"
KOKX_PRODUCTS = ("HHC", "N0B")


def load_events(events_file: Optional[Path] = None, event: Optional[str] = None,
                day: Optional[str] = None) -> pd.DataFrame:
    """Catalog rows (event, cls, start, end, …): all, one `event`, or a whole UTC `day`."""
    from analysis.radar_utils import load_event_catalog
    if day:
        d = pd.Timestamp(day).normalize()
        return pd.DataFrame({"event": [f"{d:%Y-%m-%d}_day"], "cls": ["user"],
                             "start": [d], "end": [d + pd.Timedelta("1D")]})
    ev = load_event_catalog(events_file or EVENTS_CSV)
    if event:
        ev = ev[ev.event == event]
        if ev.empty:
            raise SystemExit(f"no event {event!r} in {events_file or EVENTS_CSV}")
    return ev.reset_index(drop=True)


def select(dataset: Optional[str] = None, outfile: Optional[Path] = None,
           period: Optional[Sequence[str]] = None) -> Path:
    """Build an event catalog from the ASOS and GHCN data of `dataset` (v1: the window
    fetched by datasets.fetch_v1_asos / fetch_v1_ghcn) and write it."""
    from analysis import datasets as D
    from analysis.radar_utils import build_event_catalog, load_sensors, save_event_catalog
    name = D.resolve(dataset)
    networks, _, ghcn = load_sensors(dataset=name, verbose=False)
    if ghcn.empty:
        raise SystemExit(f"dataset {name!r} has no GHCN data; for v1 run "
                         "analysis.datasets.fetch_v1_ghcn('<start>', '<end>') first")
    if period is None:
        if name == "v1":
            period = tuple(f"{t:%Y-%m-%d}" for t in D.asos_window(D.paths("v1").asos))
        else:
            period = D.V2_PERIOD
    events = build_event_catalog(networks["ASOS"], ghcn, period=period)
    outfile = outfile or DATASET_DIR / "raw" / "radar" / f"radar_events_{name}.csv"
    outfile.parent.mkdir(parents=True, exist_ok=True)
    save_event_catalog(events, outfile)
    print(f"Wrote {len(events)} events to {outfile}")
    print(events[["event", "cls", "start", "end", "ghcn_mm", "asos_mm"]].to_string(index=False))
    return outfile


def fetch(events: pd.DataFrame, radar: str = "mrms", pad: str = "1h",
          products: Optional[Sequence[str]] = None, dataset: Optional[str] = None) -> None:
    """Fill the radar cache for every row of `events` (± `pad`).

    mrms : the MRMS products of `analysis.radar_utils.DEFAULT_PRODUCTS` (or `products`).
    kokx : KOKX Level-3 samples at the CML paths of `dataset` and on the city grid
           (default products HHC and N0B).
    """
    if radar == "mrms":
        from analysis.radar_utils import DEFAULT_PRODUCTS, fetch_event_radar
        prods = {p: DEFAULT_PRODUCTS.get(p) for p in products} if products else None
        fetch_event_radar(events, products=prods, pad=pad)
    elif radar == "kokx":
        from fetch_data.nexrad import kokx
        for ev in events.itertuples():
            a, b = ev.start - pd.Timedelta(pad), ev.end + pd.Timedelta(pad)
            kokx.fetch_window(a, b, products=tuple(products or KOKX_PRODUCTS), dataset=dataset)
            n = {p: kokx.load(a, b, p, dataset) for p in (products or KOKX_PRODUCTS)}
            print(f"  {ev.event:22s} " + "  ".join(
                f"{p}: {0 if d is None else d['t'].nunique()} scans" for p, d in n.items()), flush=True)
    else:
        raise ValueError(f"unknown radar {radar!r}; use 'mrms' or 'kokx'")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)

    sp_list = sp.add_parser("list", help="Print the catalog events")
    sp_list.add_argument("--events", type=Path, help="Event CSV (default: dataset/meta/radar_events.csv)")

    sp_select = sp.add_parser("select", help="Build an event catalog from a dataset's ASOS and GHCN data")
    sp_select.add_argument("--dataset", choices=["v1", "v2"], help="Default: the active dataset")
    sp_select.add_argument("--outfile", type=Path, help="Default: dataset/raw/radar/radar_events_<dataset>.csv")
    sp_select.add_argument("--period", nargs=2, metavar=("START", "END"), help="Days (UTC) to search")

    sp_fetch = sp.add_parser("fetch", help="Download radar for the catalog events (or one day)")
    sp_fetch.add_argument("radar", nargs="?", default="mrms", choices=["mrms", "kokx"],
                          help="Which radar to fetch (default: %(default)s)")
    sp_fetch.add_argument("--events", type=Path, help="Event CSV (default: dataset/meta/radar_events.csv)")
    sp_fetch.add_argument("--event", help="One event of the catalog, e.g. 2024-03-23_rain")
    sp_fetch.add_argument("--day", help="One UTC day (YYYY-MM-DD) instead of the catalog")
    sp_fetch.add_argument("--products", nargs="+", help="Products (default: all MRMS of the tutorial / HHC N0B)")
    sp_fetch.add_argument("--pad", default="1h", help="Time added before and after each event (default: 1h)")
    sp_fetch.add_argument("--dataset", choices=["v1", "v2"], help="kokx: whose CML paths to sample")

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.cmd == "list":
        print(load_events(args.events)[["event", "cls", "start", "end", "hours", "ghcn_mm", "asos_mm"]]
              .to_string(index=False))
    elif args.cmd == "select":
        select(args.dataset, args.outfile, args.period)
    elif args.cmd == "fetch":
        events = load_events(args.events, args.event, args.day)
        fetch(events, args.radar, args.pad, args.products, args.dataset)


if __name__ == "__main__":
    main()
