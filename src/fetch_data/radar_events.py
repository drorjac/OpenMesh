"""Fetch radar data for significant precipitation events.

Selects rain, snow, and mixed-precip events from ASOS observations, then fetches
MRMS and KOKX NEXRAD data for those events. Uses multi-source precipitation data
to pick representative days (top N by amount/intensity).

Usage::

    python src/fetch_data/radar_events.py select          # build events.csv from ASOS/GHCN
    python src/fetch_data/radar_events.py fetch mrms      # fetch MRMS for all events
    python src/fetch_data/radar_events.py fetch kokx       # fetch KOKX NEXRAD for all events
    python src/fetch_data/radar_events.py fetch --day 2024-01-19 --kind snow   # any other day
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

# Add src to path so imports work when run as script
_src = Path(__file__).resolve().parents[2] / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

import numpy as np
import pandas as pd
import xarray as xr

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = REPO_ROOT / "dataset"
EVENTS_CSV = DATASET_DIR / "meta" / "radar_events.csv"

# Event selection: two independent continuous eras (links have good data)
LINK_ERAS = [
    (pd.Timestamp("2023-11-01"), pd.Timestamp("2024-07-14")),
    (pd.Timestamp("2025-04-21"), pd.Timestamp("2026-05-31")),
]

# Selection thresholds for each event type
N_EVENTS = 5  # top N per class (rain / snow / mix)
MIN_SNOW_MM = 5.0  # liquid equivalent, station mean
MIN_SNOW_SHARE = 0.6  # fraction of precip minutes typed snow
MIN_RAIN_SHARE = 0.85  # rain events (ASOS light rain often coded 'mix')
MAX_RAIN_SNOW = 0.05  # rain events: max snow fraction
MIN_WET_MINUTES = 300  # ASOS station-minutes with any precip
MIN_GAP_DAYS = 5  # spacing between events of same type


def _daily_summary() -> pd.DataFrame:
    """Per-day precipitation amount and type from ASOS."""
    try:
        from analysis import datasets as D
        from analysis.radar_utils import load_sensors

        networks, _, _ = load_sensors(verbose=False)
        asos = networks.get("ASOS", {})
    except Exception as e:
        log.error(f"Failed to load ASOS sensors: {e}")
        return pd.DataFrame()

    if not asos:
        log.warning("No ASOS data found; returning empty event summary")
        return pd.DataFrame()

    rows = []
    for station_id, ds in asos.items():
        r = ds["rainfall"].to_pandas()  # time series
        c = ds["precip_category"].to_pandas()

        day = r.index.normalize()
        tot = r.groupby(day).sum(min_count=600)  # daily mm

        # Count precip minutes by type
        wet = c.isin(["rain", "snow", "mix"])
        for kind in ("rain", "snow", "mix"):
            rows.append(((c == kind).groupby(day).sum()).rename(kind))
        rows.append(wet.groupby(day).sum().rename("wet_minutes"))
        rows.append(tot.rename("asos_mm"))

    # Combine across stations
    D = pd.concat(rows, axis=1)
    D = D.groupby(level=0).first()

    # Fractions
    for kind in ("rain", "snow", "mix"):
        if kind in D.columns:
            D[f"{kind}_share"] = D[kind] / D["wet_minutes"].replace(0, np.nan)

    return D


def pick_events(daily: pd.DataFrame, kind: str) -> pd.DataFrame:
    """Top N events of the given kind (rain / snow / mix)."""
    if kind == "snow":
        mask = (daily.get("snow_share", 0) >= MIN_SNOW_SHARE) & (daily.get("asos_mm", 0) >= MIN_SNOW_MM)
    elif kind == "rain":
        mask = (
            (daily.get("rain_share", 0) >= MIN_RAIN_SHARE) &
            (daily.get("snow_share", 0) <= MAX_RAIN_SNOW)
        )
    else:  # "mix"
        mask = ~(daily.get("rain_share", 0) >= MIN_RAIN_SHARE) & ~(daily.get("snow_share", 0) >= MIN_SNOW_SHARE)
        mask = mask & (daily.get("wet_minutes", 0) >= MIN_WET_MINUTES)

    cand = daily[mask].copy()
    cand = cand[cand.get("wet_minutes", 0) >= MIN_WET_MINUTES]

    # Filter to link-continuous eras
    cand = cand[[any(a <= d <= b for a, b in LINK_ERAS) for d in cand.index]]
    cand = cand.sort_values("asos_mm", ascending=False)

    # Space events MIN_GAP_DAYS apart
    out = []
    for d, r in cand.iterrows():
        if all(abs((d - e).days) >= MIN_GAP_DAYS for e in out):
            out.append(d)
        if len(out) == N_EVENTS:
            break

    return cand.loc[out].assign(kind=kind)


def select(outfile: Optional[Path] = None):
    """Build event catalog (or overwrite CSV) from ASOS daily data."""
    outfile = outfile or EVENTS_CSV

    try:
        daily = _daily_summary()
    except Exception as e:
        log.error(f"Failed to build daily summary: {e}")
        return

    if daily.empty:
        log.warning("No data in daily summary; skipping event selection")
        return

    events = pd.concat([
        pick_events(daily, "snow"),
        pick_events(daily, "rain"),
        pick_events(daily, "mix"),
    ])

    outfile.parent.mkdir(parents=True, exist_ok=True)
    events.index.name = "day"
    events.to_csv(outfile)
    print(f"Wrote {len(events)} events to {outfile}")
    print(events[["kind", "asos_mm", "wet_minutes"]])


def fetch(outdir: Path, events_file: Optional[Path] = None, events: Optional[pd.DataFrame] = None,
           radar: str = "mrms", **kw):
    """Fetch radar for events in CSV or DataFrame.

    Parameters
    ----------
    outdir : Path
        Output directory for downloaded radar files.
    events_file : Path, optional
        Event CSV (default: EVENTS_CSV from dataset/meta/).
    events : pd.DataFrame, optional
        Events DataFrame (bypasses CSV if provided).
    radar : {"mrms", "kokx"}
        Radar type to fetch.
    **kw
        Options passed to the radar fetcher.
    """
    if events is None:
        events_file = events_file or EVENTS_CSV

        try:
            events = pd.read_csv(events_file, index_col="day", parse_dates=["day"])
        except FileNotFoundError:
            log.error(f"Event CSV not found: {events_file}. Run 'select' first.")
            return

    outdir.mkdir(parents=True, exist_ok=True)

    if radar == "mrms":
        _fetch_mrms(outdir, events, **kw)
    elif radar == "kokx":
        _fetch_kokx(outdir, events, **kw)
    else:
        raise ValueError(f"unknown radar {radar!r}; use 'mrms' or 'kokx'")


def _fetch_mrms(outdir: Path, events: pd.DataFrame):
    """Fetch MRMS for each event."""
    from fetch_data.mrms import MRMSClient, NYC

    client = MRMSClient()
    products = ["MultiSensor_QPE_01H_Pass2", "RadarOnly_QPE_01H", "PrecipFlag"]

    for day, row in events.iterrows():
        kind = row.get("kind", "unknown")
        start = day
        end = day + pd.Timedelta(days=1)

        for product in products:
            try:
                data = client.load(product, start, end, NYC)
                if data is None:
                    log.warning(f"No data: {product} {kind} {day:%Y-%m-%d}")
                    continue

                outfile = outdir / f"mrms_{product}_{kind}_{day:%Y%m%d}.nc"
                data.to_netcdf(outfile)
                print(f"Wrote {outfile.name}")
            except Exception as e:
                log.error(f"Failed to fetch {product} {day}: {e}")


def _fetch_kokx(outdir: Path, events: pd.DataFrame):
    """Fetch KOKX NEXRAD for each event."""
    from fetch_data.nexrad import kokx

    products = ["HHC", "N0B"]

    for day, row in events.iterrows():
        kind = row.get("kind", "unknown")
        start = day
        end = day + pd.Timedelta(days=1)

        # Fetch to cache
        kokx.fetch_window(start, end, products=products, workers=4)

        # Load and save
        for product in products:
            try:
                data = kokx.load(start, end, product)
                if data is None:
                    log.warning(f"No data: {product} {kind} {day:%Y-%m-%d}")
                    continue

                outfile = outdir / f"kokx_{product}_{kind}_{day:%Y%m%d}.parquet"
                data.to_parquet(outfile, index=False)
                print(f"Wrote {outfile.name}")
            except Exception as e:
                log.error(f"Failed to fetch {product} {day}: {e}")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sp = ap.add_subparsers(dest="cmd", required=True)

    sp_select = sp.add_parser("select", help="Build event catalog from ASOS/GHCN data")
    sp_select.add_argument("--outfile", type=Path, help="CSV output (default: dataset/meta/radar_events.csv)")

    sp_fetch = sp.add_parser("fetch", help="Download radar for events")
    sp_fetch.add_argument("radar", nargs="?", default="mrms", choices=["mrms", "kokx"],
                          help="Which radar to fetch (default: %(default)s)")
    sp_fetch.add_argument("--outdir", type=Path, default=DATASET_DIR / "raw" / "radar",
                          help="Output directory (default: %(default)s)")
    sp_fetch.add_argument("--events", type=Path, help="Event CSV (default: dataset/meta/radar_events.csv)")
    sp_fetch.add_argument("--day", help="Single day (YYYY-MM-DD) instead of CSV")
    sp_fetch.add_argument("--kind", choices=["rain", "snow", "mix"], help="Type for --day")

    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.cmd == "select":
        select(args.outfile)
    elif args.cmd == "fetch":
        events_df = None
        if args.day:
            # Single day
            day = pd.Timestamp(args.day)
            events_df = pd.DataFrame({"kind": [args.kind or "unknown"]}, index=pd.DatetimeIndex([day], name="day"))

        outdir = args.outdir / args.radar
        fetch(outdir, events_file=args.events, events=events_df, radar=args.radar)


if __name__ == "__main__":
    main()
