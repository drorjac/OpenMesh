"""Fetch MRMS radar for every event in the radar event catalog.

Usage (from the repo root):
    python src/fetch_data/mrms/fetch_events.py                 # all events, default products
    python src/fetch_data/mrms/fetch_events.py --events 2024-03-23_rain --products PrecipFlag

Reads dataset/meta/radar_events.csv (built by analysis.radar_utils.build_event_catalog)
and fills the MRMS cache under dataset/raw/radar/mrms/cache. Safe to re-run: cached
fields are not downloaded again. Default products: hourly MultiSensor_QPE_01H_Pass2,
and PrecipFlag + PrecipRate subsampled to 10 min, each padded by 1 h around the event.
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from analysis.radar_utils import DEFAULT_PRODUCTS, fetch_event_radar, load_event_catalog  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--events', nargs='*', help='event names (default: all in the catalog)')
    ap.add_argument('--products', nargs='*', default=list(DEFAULT_PRODUCTS),
                    help='MRMS products (default: %(default)s)')
    ap.add_argument('--pad', default='1h', help='padding around each event (default: 1h)')
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format='%(levelname)s %(message)s')

    events = load_event_catalog()
    if args.events:
        events = events[events['event'].isin(args.events)]
    products = {p: DEFAULT_PRODUCTS.get(p) for p in args.products}
    summary = fetch_event_radar(events, products=products, pad=args.pad)
    print(summary.groupby('product')[['n_fields', 'n_missing']].sum())


if __name__ == '__main__':
    main()
