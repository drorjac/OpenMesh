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
from config import OUTPUT_DIRS, PROJECT_ROOT, DATASET_DIR, get_output_dir


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
    }
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
    import os
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
  python main.py status                                Show dataset status
  python main.py all                                   Run all pipelines
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    # OpenMesh command
    sub_om = subparsers.add_parser('openmesh', help='Download OpenMesh dataset from Zenodo')
    
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
    
    # Status command
    sub_status = subparsers.add_parser('status', help='Show dataset status')
    
    # All command
    sub_all = subparsers.add_parser('all', help='Run all pipelines with defaults')
    
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
    elif args.command == 'status':
        show_status()
    elif args.command == 'all':
        run_all()


if __name__ == '__main__':
    main()