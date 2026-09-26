#!/usr/bin/env python3
"""
OpenMesh Data Fetching CLI
==========================

Command-line interface to download and fetch weather data from multiple sources.

Usage:
    # From src/fetch_data/ directory:
    python main.py openmesh              # Download & extract OpenMesh dataset
    python main.py asos -s JFK LGA --start 2024-01-01 --end 2024-01-31
    python main.py wu -s KNYNEWYO1805 --start 2024-01-01 --end 2024-01-31
    python main.py mrms --start 2024-01-09 --end 2024-01-10
    python main.py status                # Show dataset status
    python main.py all                   # Run all pipelines with defaults
    
    # Or make executable and run directly:
    ./main.py openmesh
    ./main.py asos -s JFK LGA --start 2024-01-01 --end 2024-01-31

Examples:
    # Download OpenMesh from Zenodo
    python main.py openmesh
    
    # Fetch ASOS data for NYC airports
    python main.py asos -s JFK LGA NYC --start 2024-01-01 --end 2024-01-30
    
    # Fetch Weather Underground PWS data
    python main.py wu -s KNYNEWYO1805 KNYNEWYO1850 --start 2024-01-01 --end 2024-01-30

    # Fetch MRMS radar for NYC (hourly QPE; add 2-min products with --products)
    python main.py mrms --start 2024-01-09 --end 2024-01-10
    python main.py mrms --start 2024-01-09 --end 2024-01-10 --products PrecipFlag --freq 10min
    python main.py mrms --events                # every event in dataset/meta/radar_events.csv
    python main.py mrms --list-products         # all ~240 MRMS products
    python main.py mrms --start 2024-01-10 --end 2024-01-10T02:00 --products MergedReflectivityQCComposite
    python main.py mrms --events-file my_events.csv --bbox 40.70 40.80 -74.02 -73.92
    
    # Show current dataset structure
    python main.py status
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))

# Import ONLY from main config (shared paths and settings)
from config import OUTPUT_DIRS, PROJECT_ROOT, DATASET_DIR


# =============================================================================
# Default Configuration (edit these for quick runs without CLI args)
# =============================================================================

DEFAULTS = {
    'asos': {
        'stations': ['JFK', 'LGA', 'NYC'],
        'start': '2024-01-01',
        'end': '2024-01-30',
    },
    'wu': {
        'stations': ['KNYNEWYO1805', 'KNYNEWYO1850'],
        'start': '2024-01-01',
        'end': '2024-01-30',
    },
    'mrms': {
        'products': ['MultiSensor_QPE_01H_Pass2'],
        'start': '2024-01-09',
        'end': '2024-01-10',
    },
}


# =============================================================================
# Pipeline Functions
# =============================================================================

def run_openmesh(verbose=True):
    """Download and extract OpenMesh dataset from Zenodo."""
    from OpenMesh.openmesh import run_openmesh_pipeline
    
    result = run_openmesh_pipeline(verbose=verbose)
    return result is not None


def run_asos(stations, start_date, end_date, save_type='standard', resample_interval='5min', 
             save_api_response=False, verbose=True):
    """Fetch ASOS data from IEM."""
    from noaa_asos.asos_fetch import fetch_all_stations_1min, process_all_stations, resample_all_stations, save_asos
    from datetime import datetime
    
    # Parse dates if strings
    if isinstance(start_date, str):
        start_date = datetime.strptime(start_date, '%Y-%m-%d')
    if isinstance(end_date, str):
        end_date = datetime.strptime(end_date, '%Y-%m-%d')
    
    # Fetch raw data
    if verbose:
        print(f"Fetching ASOS data for {len(stations)} stations...")
    raw_data = fetch_all_stations_1min(stations, start_date, end_date, verbose=verbose)
    
    if not raw_data:
        if verbose:
            print("✗ No data fetched")
        return False
    
    # Process to metric (always needed for standard and resampled types)
    processed_data = None
    resampled_data = None
    
    if save_type in ['standard', 'resampled']:
        if verbose:
            print("Converting to metric units...")
        processed_data = process_all_stations(raw_data, verbose=verbose)
    
    # Resample if needed
    if save_type == 'resampled':
        if verbose:
            print(f"Resampling to {resample_interval} intervals...")
        resampled_data = resample_all_stations(processed_data, interval=resample_interval, verbose=verbose)
    
    # Prepare all datasets dictionary
    all_asos_datasets = {}
    if raw_data:
        all_asos_datasets['raw'] = raw_data
    if processed_data:
        all_asos_datasets['standard'] = processed_data
    if resampled_data:
        all_asos_datasets['resampled'] = resampled_data
    
    # Save selected type
    if verbose:
        type_name = {'raw': 'raw', 'standard': 'standardized', 'resampled': f'resampled ({resample_interval})'}[save_type]
        print(f"Saving {type_name} data...")
    
    save_asos(
        type=save_type,
        datasets=all_asos_datasets,
        output_dir=OUTPUT_DIRS['asos'],
        resample_interval=resample_interval if save_type == 'resampled' else None,
        overwrite=True
    )
    
    # Save API response data if requested (to subfolder)
    if save_api_response:
        api_response_dir = OUTPUT_DIRS['asos'] / 'api_response'
        api_response_dir.mkdir(parents=True, exist_ok=True)
        if verbose:
            print(f"Saving API response data to {api_response_dir}...")
        save_asos(type='raw', datasets={'raw': raw_data}, output_dir=api_response_dir, overwrite=True)
    
    if verbose:
        # Get data dict for summary
        data_for_summary = raw_data if save_type == 'raw' else (resampled_data if save_type == 'resampled' else processed_data)
        total_rows = sum(len(df) for df in data_for_summary.values())
        print(f"✓ Complete: {len(data_for_summary)} stations, {total_rows:,} total rows")
    
    return True


def run_wu(stations, start_date, end_date, api_key=None, all_stations=False, save_api_response=False, verbose=True):
    """Fetch Weather Underground PWS data."""
    from weather_underground.wu_fetch import run_wu_pipeline, save_wu, read_pws_metadata, get_station_list
    
    # Load all stations from metadata if requested
    if all_stations:
        if verbose:
            print("Loading all stations from metadata...")
        pws_metadata = read_pws_metadata()
        stations = get_station_list(pws_metadata)
        if verbose:
            print(f"✓ Loaded {len(stations)} stations from metadata")
    elif stations is None:
        # Use defaults if neither stations nor --all-stations provided
        stations = DEFAULTS['wu']['stations']
        if verbose:
            print(f"Using default stations: {stations}")
    
    # Get API key (priority: direct parameter > env var > config file)
    from weather_underground.config import get_api_key
    try:
        api_key = get_api_key(api_key=api_key, raise_error=False)
    except Exception:
        api_key = None
    
    if not api_key:
        print("✗ No API key found. Options:\n"
              "  1. Use --api-key flag: --api-key YOUR_KEY\n"
              "  2. Set environment variable: export WU_API_KEY='your_key'\n"
              "  3. Add to weather_underground/config.py")
        return False
    
    # Parse dates
    if isinstance(start_date, str):
        start = datetime.strptime(start_date, '%Y-%m-%d')
    else:
        start = start_date
    if isinstance(end_date, str):
        end = datetime.strptime(end_date, '%Y-%m-%d')
    else:
        end = end_date
    
    # Run pipeline
    results = run_wu_pipeline(
        api_key=api_key,
        station_ids=stations,
        start_date=start,
        end_date=end,
        units='m',
        output_dir=str(OUTPUT_DIRS['wu']),
        save_data=False  # We'll save manually
    )
    
    if not results or 'dataframes' not in results:
        print("✗ No data fetched")
        return False
    
    # Extract processed data
    processed_data = {sid: dfs['clean'] for sid, dfs in results['dataframes'].items()}
    
    # Save processed data (default)
    if verbose:
        print("\nSaving processed data...")
    save_wu(processed_data=processed_data, output_dir=OUTPUT_DIRS['wu'], overwrite=True)
    
    # Save API response data if requested (to subfolder)
    if save_api_response:
        api_response_dir = OUTPUT_DIRS['wu'] / 'api_response'
        api_response_dir.mkdir(parents=True, exist_ok=True)
        # Extract raw DataFrames from results
        raw_data = {sid: dfs.get('raw') for sid, dfs in results['dataframes'].items() if 'raw' in dfs}
        if raw_data:
            if verbose:
                print(f"Saving API response data to {api_response_dir}...")
            save_wu(raw_data=raw_data, output_dir=api_response_dir, overwrite=True)
    
    # Summary
    summary = results.get('summary', {})
    if verbose:
        print(f"\n✓ Complete: {summary.get('stations_with_data', len(processed_data))} stations")
    
    return True


def run_mrms(start_date=None, end_date=None, products=None, freq=None, events=False,
             events_file=None, bbox=None, list_products=False, verbose=True):
    """Fetch MRMS radar into dataset/raw/radar/mrms/cache (see fetch_data/mrms).

    products : any MRMS product — registered (e.g. PrecipRate), full archive name
        (e.g. MergedRhoHV_00.50) or unique short name; list them with list_products.
    bbox : (lat_min, lat_max, lon_min, lon_max) to crop; default NYC.
    events / events_file : fetch our radar event catalog, or your CSV (start, end),
        with `products` (default set if not given) instead of one window.
    """
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from fetch_data.mrms import NYC, Domain, MRMSClient, MRMSError, usable_freq
    client = MRMSClient()
    domain = Domain(*bbox, name='custom') if bbox else NYC
    try:
        if list_products:
            names = client.list_products()
            print(f"{len(names)} MRMS products on AWS (CONUS):")
            for n in names:
                print('  ', n)
            return True
        if events or events_file:
            from analysis.radar_utils import DEFAULT_PRODUCTS, fetch_event_radar, load_event_catalog
            catalog = load_event_catalog(events_file) if events_file else load_event_catalog()
            prods = {p: freq or DEFAULT_PRODUCTS.get(p) for p in products} if products else None
            summary = fetch_event_radar(catalog, products=prods, domain=domain,
                                        client=client, verbose=verbose)
            print(summary.groupby('product')[['n_fields', 'n_missing']].sum())
            return bool((summary['n_fields'] > 0).all())
        ok = True
        for product in products:
            p = client.resolve_product(product)
            da = client.load(p, start_date, end_date, domain, freq=usable_freq(p, freq))
            n_miss = len(da.attrs.get('missing_times', []))
            if verbose:
                print(f"✓ {p.name}: {da.sizes['time']} fields "
                      f"({da.sizes['lat']}×{da.sizes['lon']} cells), {n_miss} missing"
                      f"  → {client.cache_dir}/{p.name}/{domain.key}")
            ok &= da.sizes['time'] > 0
        return ok
    except (MRMSError, ValueError, KeyError) as e:
        print(f"✗ MRMS: {e}")
        return False


def show_status():
    """Show current dataset structure and contents."""
    print("\n" + "="*60)
    print("DATASET STATUS")
    print("="*60)
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Dataset dir:  {DATASET_DIR}")
    print()
    
    # Check each output directory
    for name, path in OUTPUT_DIRS.items():
        if name in ['wu_pws', 'openmesh']:  # Skip aliases
            continue
        
        if name == 'mrms':            # nested per-product/day cache: summarise instead
            sys.path.insert(0, str(Path(__file__).parent.parent))
            from fetch_data.mrms import cache_inventory
            inv = cache_inventory(path / 'cache')
            if inv.empty:
                print(f"○ {name}: empty")
                continue
            print(f"✓ {name}: {inv['days'].sum()} daily files, {inv['size_mb'].sum():.1f} MB")
            for r in inv.itertuples():
                print(f"    {r.product:27s} {r.domain:24s} {r.days:4d} days  {r.first}–{r.last}  {r.size_mb:.1f} MB")
            continue
        if path.exists():
            files = list(path.glob('*'))
            file_count = len([f for f in files if f.is_file()])
            if file_count > 0:
                print(f"✓ {name}: {file_count} files")
                for f in sorted(files)[:5]:
                    if f.is_file():
                        size_mb = f.stat().st_size / (1024 * 1024)
                        print(f"    {f.name} ({size_mb:.1f} MB)")
                if file_count > 5:
                    print(f"    ... and {file_count - 5} more")
            else:
                print(f"○ {name}: empty")
        else:
            print(f"○ {name}: not created")
    print()


def run_all():
    """Run all pipelines with default settings."""
    print("\n" + "="*60)
    print("RUNNING ALL PIPELINES")
    print("="*60)
    
    results = {}
    
    # OpenMesh
    results['openmesh'] = run_openmesh()
    
    # ASOS
    results['asos'] = run_asos(
        stations=DEFAULTS['asos']['stations'],
        start_date=DEFAULTS['asos']['start'],
        end_date=DEFAULTS['asos']['end']
    )
    
    # WU
    results['wu'] = run_wu(
        stations=DEFAULTS['wu']['stations'],
        start_date=DEFAULTS['wu']['start'],
        end_date=DEFAULTS['wu']['end']
    )
    
    # MRMS radar
    results['mrms'] = run_mrms(
        start_date=DEFAULTS['mrms']['start'],
        end_date=DEFAULTS['mrms']['end'],
        products=DEFAULTS['mrms']['products'],
    )

    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    for name, success in results.items():
        status = "✓" if success else "✗"
        print(f"  {status} {name}")
    
    return all(results.values())


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='OpenMesh Data Fetching CLI',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py openmesh                              Download OpenMesh dataset
  python main.py asos -s JFK LGA                       Fetch ASOS (saves standard by default)
  python main.py asos -s JFK LGA --type raw            Save raw ASOS data
  python main.py asos -s JFK LGA --type standard       Save standardized ASOS data
  python main.py asos -s JFK LGA --type resampled --resample-interval 5min  Save resampled ASOS data
  python main.py wu -s KNYNEWYO1805                    Fetch WU with defaults  
  python main.py mrms --start 2024-01-09 --end 2024-01-10   Fetch MRMS hourly QPE for NYC
  python main.py mrms --events                         Fetch MRMS for the radar event catalog
  python main.py status                                Show dataset status
  python main.py all                                   Run all pipelines
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    # OpenMesh command
    subparsers.add_parser('openmesh', help='Download OpenMesh dataset from Zenodo')
    
    # ASOS command
    sub_asos = subparsers.add_parser('asos', help='Fetch ASOS data from IEM')
    sub_asos.add_argument('-s', '--stations', nargs='+', 
                         default=DEFAULTS['asos']['stations'],
                         help='Station IDs (e.g., JFK LGA NYC)')
    sub_asos.add_argument('--start', default=DEFAULTS['asos']['start'],
                         help='Start date (YYYY-MM-DD)')
    sub_asos.add_argument('--end', default=DEFAULTS['asos']['end'],
                         help='End date (YYYY-MM-DD)')
    sub_asos.add_argument('--type', choices=['raw', 'standard', 'resampled'], default='standard',
                         help='Type of data to save: raw (US units), standard (metric, 1-min), or resampled (aggregated intervals)')
    sub_asos.add_argument('--resample-interval', default='5min',
                         help='Resampling interval for resampled type (e.g., 5min, 10min, 15min, 1H). Default: 5min')
    sub_asos.add_argument('--api-response', action='store_true',
                         help='Also save API response data (raw US units) to api_response/ subfolder')
    
    # WU command
    sub_wu = subparsers.add_parser('wu', help='Fetch Weather Underground PWS data')
    sub_wu.add_argument('-s', '--stations', nargs='+',
                       default=None,
                       help='Station IDs (e.g., KNYNEWYO1805). If not provided, uses --all-stations or defaults')
    sub_wu.add_argument('--all-stations', action='store_true',
                       help='Load all stations from dataset/meta/pws_metadata.csv')
    sub_wu.add_argument('--start', default=DEFAULTS['wu']['start'],
                       help='Start date (YYYY-MM-DD)')
    sub_wu.add_argument('--end', default=DEFAULTS['wu']['end'],
                       help='End date (YYYY-MM-DD)')
    sub_wu.add_argument('--api-key', help='WU API key (or set WU_API_KEY env var)')
    sub_wu.add_argument('--api-response', action='store_true',
                       help='Also save API response data (original format) to api_response/ subfolder')
    
    # MRMS radar command
    sub_mrms = subparsers.add_parser('mrms', help='Fetch MRMS radar (NOAA) for NYC')
    sub_mrms.add_argument('--start', default=DEFAULTS['mrms']['start'],
                          help='Start date/time, UTC (YYYY-MM-DD[ HH:MM])')
    sub_mrms.add_argument('--end', default=DEFAULTS['mrms']['end'],
                          help='End date/time, UTC (YYYY-MM-DD[ HH:MM])')
    sub_mrms.add_argument('--products', nargs='+', default=None,
                          help='Any MRMS products, e.g. MultiSensor_QPE_01H_Pass2 PrecipFlag '
                               'MergedReflectivityQCComposite (see --list-products; default: '
                               f"{DEFAULTS['mrms']['products']}, or the event set with --events)")
    sub_mrms.add_argument('--freq', default=None,
                          help='Subsample 2-min products, e.g. 10min (default: native cadence)')
    sub_mrms.add_argument('--events', action='store_true',
                          help='Fetch every event in dataset/meta/radar_events.csv instead')
    sub_mrms.add_argument('--events-file',
                          help='Fetch the events in your CSV (columns start, end[, event]) instead')
    sub_mrms.add_argument('--bbox', nargs=4, type=float,
                          metavar=('LAT_MIN', 'LAT_MAX', 'LON_MIN', 'LON_MAX'),
                          help='Area to crop (default: NYC 40.48 40.93 -74.27 -73.68)')
    sub_mrms.add_argument('--list-products', action='store_true',
                          help='List every product in the MRMS archive and exit')

    # Status command
    subparsers.add_parser('status', help='Show dataset status')
    
    # All command
    subparsers.add_parser('all', help='Run all pipelines with defaults')
    
    args = parser.parse_args()
    
    if args.command is None:
        parser.print_help()
        return
    
    # Execute command
    if args.command == 'openmesh':
        run_openmesh()
    elif args.command == 'asos':
        run_asos(args.stations, args.start, args.end, args.type, args.resample_interval, args.api_response)
    elif args.command == 'wu':
        run_wu(args.stations, args.start, args.end, args.api_key, args.all_stations, args.api_response)
    elif args.command == 'mrms':
        products = args.products or (None if (args.events or args.events_file)
                                     else DEFAULTS['mrms']['products'])
        run_mrms(args.start, args.end, products, args.freq, args.events, args.events_file,
                 args.bbox, args.list_products)
    elif args.command == 'status':
        show_status()
    elif args.command == 'all':
        run_all()


if __name__ == '__main__':
    main()