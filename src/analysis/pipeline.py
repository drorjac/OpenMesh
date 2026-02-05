"""
Data Pipeline - Complete data operations for OpenMesh analysis

Handles all data operations:
- Fetching from APIs (ASOS, Weather Underground)
- Loading from files (CSV, NetCDF)
- Processing and standardization with DYNAMIC parameter extraction
- Unified format conversion

This module consolidates all data I/O operations.
"""

import pandas as pd
import xarray as xr
import netCDF4 as nc
import os
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Tuple, Any, List, Union
import warnings
import folium
import contextlib
warnings.filterwarnings('ignore')

# Import WU API key function
try:
    from fetch_data.weather_underground.config import get_api_key
except ImportError:
    def get_api_key():
        return os.getenv('WU_API_KEY')
try:
    from fetch_data.OpenMesh.openmesh import load_pws as _load_pws_fetch
    from fetch_data.OpenMesh.openmesh import run_openmesh_pipeline as _run_openmesh_pipeline
    from fetch_data.OpenMesh.openmesh import run_pws_wu_pipeline as _run_pws_wu_pipeline
except ImportError:
    _load_pws_fetch = None
    _run_openmesh_pipeline = None
    _run_pws_wu_pipeline = None


# ============================================================================
# CONFIGURATION & PATHS
# ============================================================================

def get_default_paths():
    """Get default data paths relative to project structure."""
    base_dir = Path(__file__).parent.parent.parent
    dataset_dir = base_dir / "dataset"
    
    return {
        'asos': dataset_dir / 'raw' / 'fetched' / 'asos',
        'wu': dataset_dir / 'raw' / 'fetched' / 'wu',
        'openmesh_raw': dataset_dir / 'raw' / 'openmesh',
        'openmesh_meta': dataset_dir / 'meta' ,
        'meta': dataset_dir / 'meta',
        'links': dataset_dir / 'links',
        'weather_stations': dataset_dir / 'weather_station',
    }


def _first_existing(candidates):
    """Return first path that exists, or None. Handles dataset/meta vs meta/openmesh duplicates."""
    for p in candidates:
        if p is not None and Path(p).exists():
            return Path(p)
    return None


# ============================================================================
# METADATA LOADER
# ============================================================================

def load_metadata(paths: Optional[Dict[str, Path]] = None) -> Dict[str, pd.DataFrame]:
    """Load all metadata files. Tries multiple locations to handle meta/ vs meta/openmesh/ duplicates."""
    if paths is None:
        paths = get_default_paths()
    
    meta = paths['meta']
    om = paths['openmesh_meta']
    
    print("=" * 70)
    print("LOADING METADATA")
    print("=" * 70)
    
    metadata = {}
    
    # ASOS: meta/ or meta/openmesh/
    asos_file = _first_existing([meta / 'ASOS_stations.csv', om / 'ASOS_stations.csv'])
    if asos_file is not None:
        metadata['asos'] = pd.read_csv(asos_file)
        print(f"✓ ASOS: {len(metadata['asos'])} stations ({asos_file.name})")
    else:
        metadata['asos'] = pd.DataFrame()
        print(f"⚠ ASOS: Not found")
    
    # WU: meta/ or meta/openmesh/
    wu_file = _first_existing([meta / 'pws_metadata.csv', om / 'pws_metadata.csv'])
    if wu_file is not None:
        metadata['wu'] = pd.read_csv(wu_file)
        print(f"✓ WU: {len(metadata['wu'])} stations ({wu_file.name})")
    else:
        metadata['wu'] = pd.DataFrame()
        print(f"⚠ WU: Not found")
    
    # OpenMesh links: meta/openmesh/ or meta/ or legacy links/
    links_file = _first_existing([
        om / 'links_metadata.csv',
        meta / 'links_metadata.csv',
        paths.get('links', meta) / 'links_metadata.csv',
    ])
    if links_file is not None:
        metadata['openmesh_links'] = pd.read_csv(links_file)
        print(f"✓ OpenMesh Links: {len(metadata['openmesh_links'])} sublinks ({links_file.name})")
    else:
        metadata['openmesh_links'] = pd.DataFrame()
        print(f"⚠ OpenMesh Links: Not found")
    
    print("=" * 70)
    
    return metadata


# ============================================================================
# FETCH OPERATIONS (API calls)
# ============================================================================

def fetch_asos_data(
    stations: list,
    start_date: datetime,
    end_date: datetime
) -> Tuple[Dict[str, pd.DataFrame], Optional[str]]:
    """Fetch ASOS data from API."""
    if not start_date or not end_date:
        print("⚠ START_DATE and END_DATE not defined, skipping fetch")
        return {}, None

    # Normalize station IDs so both ICAO ('KJFK') and IATA ('JFK') work.
    # IEM 1‑minute ASOS endpoint expects 3‑letter IDs like 'JFK', 'LGA', 'NYC'.
    normalized_stations: list[str] = []
    for sid in stations:
        if not isinstance(sid, str):
            continue
        s = sid.strip().upper()
        # Common US case: drop leading 'K' from ICAO code
        if len(s) == 4 and s.startswith("K"):
            normalized_stations.append(s[1:])
        else:
            normalized_stations.append(s)
    if not normalized_stations:
        print("⚠ No valid ASOS station IDs after normalization, skipping fetch")
        return {}, None
    stations = normalized_stations
    
    try:
        from fetch_data.noaa_asos.asos_fetch import (
            fetch_all_stations_1min,
            process_all_stations
        )
        
        print(f"  Fetching ASOS for period: {start_date.date()} to {end_date.date()}")
        print(f"  Stations: {stations}")
        
        raw_data = fetch_all_stations_1min(
            station_ids=stations,
            start_date=start_date,
            end_date=end_date,
            verbose=True
        )
        
        if raw_data:
            asos_data = process_all_stations(raw_data, verbose=True)
            asos_date_range = f"{start_date.strftime('%Y-%m-%d')}_{end_date.strftime('%Y-%m-%d')}"
            
            print(f"  ✓ ASOS data fetched and processed")
            print(f"    Stations: {len(asos_data)}")
            for station_id, df in list(asos_data.items())[:2]:
                print(f"      {station_id}: {len(df):,} rows")
            if len(asos_data) > 2:
                print(f"      ... and {len(asos_data) - 2} more")
            return asos_data, asos_date_range
        else:
            print(f"  ⚠ No ASOS data fetched")
            return {}, None
    except Exception as e:
        print(f"  ⚠ Error fetching ASOS data: {e}")
        return {}, None


def fetch_wu_data(
    stations: Optional[list],
    start_date: datetime,
    end_date: datetime,
    units: str = 'm',
    api_key: Optional[str] = None
) -> Tuple[Dict[str, pd.DataFrame], Optional[str]]:
    """Fetch Weather Underground data from API."""
    if api_key is None:
        api_key = get_api_key()
    
    if not api_key or not api_key.strip():
        print(f"  ⚠ WU_API_KEY not found")
        return {}, None
    
    if not start_date or not end_date:
        print(f"  ⚠ START_DATE and END_DATE not defined")
        return {}, None
    
    try:
        from fetch_data.weather_underground.wu_fetch import (
            run_wu_pipeline,
            get_station_list,
            read_pws_metadata
        )
        
        print(f"  ✓ API key found")
        print(f"  Fetching for period: {start_date.date()} to {end_date.date()}")
        
        if stations is None or stations == 'all':
            pws_metadata = read_pws_metadata()
            wu_station_list = get_station_list(pws_metadata)
            print(f"    Loaded {len(wu_station_list)} stations from metadata")
        else:
            wu_station_list = stations
            print(f"    Using {len(wu_station_list)} specified stations")
        
        results = run_wu_pipeline(
            api_key=api_key,
            station_ids=wu_station_list,
            start_date=start_date,
            end_date=end_date,
            units=units,
            fetch_options={'historical': True},
            output_dir=None,
            save_data=False
        )
        
        if results and results.get('dataframes'):
            wu_data = {station_id: dfs['clean'] for station_id, dfs in results['dataframes'].items()}
            wu_date_range = f"{start_date.strftime('%Y-%m-%d')}_{end_date.strftime('%Y-%m-%d')}"
            
            print(f"  ✓ WU data fetched and processed")
            print(f"    Stations: {len(wu_data)}")
            for station_id, df in list(wu_data.items())[:2]:
                if 'datetime' in df.columns:
                    print(f"      {station_id}: {len(df):,} rows")
            if len(wu_data) > 2:
                print(f"      ... and {len(wu_data) - 2} more")
            return wu_data, wu_date_range
        else:
            print(f"  ⚠ No WU data fetched")
            return {}, None
    except Exception as e:
        print(f"  ⚠ Error fetching WU data: {e}")
        return {}, None


# ================================d============================================
# LOAD OPERATIONS (from files)
# ============================================================================

def load_wu_from_files(
    output_dir: Path,
    target_date_range: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None
) -> Tuple[Dict[str, pd.DataFrame], Optional[str]]:
    """Load Weather Underground data from saved CSV files."""
    try:
        csv_files = sorted(output_dir.glob('WU_*.csv'))
        if not csv_files:
            print("⚠ No WU CSV files found")
            return {}, None
        
        print(f"Found {len(csv_files)} WU file(s)")
        print("-" * 70)
        
        all_data = {}
        for file in csv_files:
            match = re.search(r'WU_(\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2})\.csv', file.name)
            if match:
                file_date_range = match.group(1)
                df = pd.read_csv(file)
                
                if 'datetime' in df.columns:
                    df['datetime'] = pd.to_datetime(df['datetime'])
                
                stations = df['station_id'].unique()
                station_data = {}
                for station in stations:
                    station_df = df[df['station_id'] == station].copy()
                    station_data[station] = station_df
                
                all_data[file_date_range] = station_data
                print(f"Loading: {file.name}... ✓ {len(stations)} stations, {len(df):,} total rows")
        
        if not all_data:
            return {}, None
        
        # Select which dataset to use
        if target_date_range and target_date_range in all_data:
            wu_date_range = target_date_range
            wu_data = all_data[target_date_range]
            print(f"\n✓ Selected: {wu_date_range} (exact match)")
        elif start_date and end_date:
            target_key = f"{start_date.strftime('%Y-%m-%d')}_{end_date.strftime('%Y-%m-%d')}"
            
            if target_key in all_data:
                wu_date_range = target_key
                wu_data = all_data[target_key]
                print(f"\n✓ Selected: {wu_date_range} (exact match)")
            else:
                available_keys = list(all_data.keys())
                print(f"  Available: {available_keys[:2]}" + (f" (+{len(available_keys)-2} more)" if len(available_keys) > 2 else ""))
                
                # Find best match based on both start and end dates, and number of stations
                def date_match_score(key):
                    try:
                        file_start_str, file_end_str = key.split('_')
                        file_start = datetime.strptime(file_start_str, '%Y-%m-%d')
                        file_end = datetime.strptime(file_end_str, '%Y-%m-%d')
                        
                        # Calculate total difference (start date diff + end date diff)
                        start_diff = abs((file_start - start_date).days)
                        end_diff = abs((file_end - end_date).days)
                        total_diff = start_diff + end_diff
                        
                        return total_diff
                    except:
                        return 999999  # Invalid date format
                
                # Sort by match score, then by number of stations (more is better)
                scored = [(key, date_match_score(key), len(all_data[key])) 
                         for key in available_keys]
                scored.sort(key=lambda x: (x[1], -x[2]))  # Sort by score (asc), then by stations (desc)
                
                best_key = scored[0][0]
                best_score = scored[0][1]
                best_stations = scored[0][2]
                wu_date_range = best_key
                wu_data = all_data[best_key]
                print(f"  ✓ Selected: {wu_date_range} (best match)")
                print(f"    Date difference: {best_score} days, Stations: {best_stations}")
        else:
            wu_date_range = max(all_data.keys())
            wu_data = all_data[wu_date_range]
            print(f"\n✓ Selected: {wu_date_range} (most recent)")
        
        print(f"  Stations: {list(wu_data.keys())[:5]}{'...' if len(wu_data) > 5 else ''}")
        return wu_data, wu_date_range
        
    except Exception as e:
        print(f"⚠ Error loading WU data: {e}")
        return {}, None


def load_asos_from_files(
    output_dir: Path,
    date_range: Optional[str] = None
) -> Tuple[Dict[str, pd.DataFrame], Optional[str]]:
    """Load ASOS data from saved CSV files."""
    try:
        from fetch_data.noaa_asos.asos_fetch import load_all_data
        
        all_asos = load_all_data(output_dir=output_dir, prefix='standard', verbose=True)
        
        if all_asos:
            if date_range and date_range in all_asos:
                asos_data = all_asos[date_range]
                asos_range = date_range
                print(f"\n✓ Using specified ASOS data: {asos_range}")
            else:
                asos_range = max(all_asos.keys())
                asos_data = all_asos[asos_range]
                print(f"\n✓ Using ASOS data (most recent): {asos_range}")
            
            print(f"  Available: {list(all_asos.keys())}")
            print(f"  Stations: {list(asos_data.keys())}")
            for station_id, df in asos_data.items():
                print(f"    {station_id}: {len(df):,} rows")
            return asos_data, asos_range
        else:
            print("⚠ No ASOS data found")
            return {}, None
    except Exception as e:
        print(f"⚠ Error loading ASOS data: {e}")
        return {}, None


def load_openmesh_cml(
        cml_file: Optional[Union[str, Path]] = None,
        metadata_file: Optional[Union[str, Path]] = None,
        verbose: bool = True
) -> Tuple[xr.Dataset, pd.DataFrame]:
    """Load OpenMesh CML (Microwave Links) dataset."""
    paths = get_default_paths()

    if cml_file is None:
        cml_file = paths['links'] / "ds_openmesh.nc"
    else:
        cml_file = Path(cml_file)

    if metadata_file is None:
        metadata_file = _first_existing([
            paths['openmesh_meta'] / 'links_metadata.csv',
            paths['meta'] / 'links_metadata.csv',
            paths['links'] / 'links_metadata.csv',
        ]) or (paths['links'] / 'links_metadata.csv')
    else:
        metadata_file = Path(metadata_file)

    if not cml_file.exists():
        raise FileNotFoundError(f"CML file not found: {cml_file.name}")

    ds_cml = xr.open_dataset(cml_file)

    df_metadata = None
    if metadata_file.exists():
        df_metadata = pd.read_csv(metadata_file)
    else:
        df_metadata = pd.DataFrame()

    if verbose:
        time_start = pd.to_datetime(ds_cml.time.values[0]).strftime('%Y-%m-%d')
        time_end = pd.to_datetime(ds_cml.time.values[-1]).strftime('%Y-%m-%d')
        print(
            f"  Links: {cml_file.name} → {len(ds_cml.cml_id)} links, {len(ds_cml.time):,} pts ({time_start} to {time_end})")
        if len(df_metadata) > 0:
            print(f"  Metadata: {metadata_file.name} → {len(df_metadata)} sublinks")

    return ds_cml, df_metadata


def load_pws_from_netcdf(
        pws_file: Optional[Union[str, Path]] = None,
        file_type: str = 'sample',
        verbose: bool = True
) -> Dict[str, xr.Dataset]:
    """Load PWS data from NetCDF file."""
    paths = get_default_paths()

    if pws_file is not None:
        pws_file = Path(pws_file)
    else:
        if file_type.lower() not in ('sample', 'full'):
            raise ValueError(f"file_type must be 'sample' or 'full', got '{file_type}'")
        filename = "pws_opensense_sample_jan.nc" if file_type.lower() == 'sample' else "pws_wu_os.nc"
        pws_file = paths['openmesh_raw'] / filename

    if not pws_file.exists():
        raise FileNotFoundError(f"PWS file not found: {pws_file.name}")

    # Always use our own loader (skip _load_pws_fetch to control printing)
    nc_file = nc.Dataset(pws_file, 'r')
    station_ids = list(nc_file.groups.keys())
    nc_file.close()

    pws_data = {}
    for station_id in station_ids:
        station_ds = xr.open_dataset(pws_file, group=station_id, engine='netcdf4')
        pws_data[station_id] = station_ds

    if verbose:
        print(f"  PWS: {pws_file.name} → {len(pws_data)} stations")

    return pws_data

def load_openmesh_netcdf(paths, force_redownload=False):
    """Smart loader: checks files → extracts from zip → fetches if needed."""
    import zipfile
    
    links_file = paths['openmesh_raw'] / 'ds_openmesh.nc'
    pws_file = paths['openmesh_raw'] / 'pws_wu_os.nc'
    links_meta_file = _first_existing([
        paths['openmesh_meta'] / 'links_metadata.csv',
        paths['meta'] / 'links_metadata.csv',
        paths.get('links', paths['meta']) / 'links_metadata.csv',
    ]) or (paths['openmesh_meta'] / 'links_metadata.csv')
    zip_file = paths['openmesh_raw'].parent / 'openmesh_data.zip'
    
    # Step 1: Try to load existing files
    if links_file.exists() and pws_file.exists() and not force_redownload:
        print("📊 Loading existing NetCDF files...")
        ds_links, links_meta = load_openmesh_cml(links_file, links_meta_file)
        pws_data = load_pws_from_netcdf(pws_file)
        print(f"✓ Links: {len(ds_links.cml_id)} links")
        print(f"✓ PWS: {len(pws_data)} stations")
        return ds_links, links_meta, pws_data
    
    # Step 2: Try to extract from zip
    if zip_file.exists():
        print(f"📦 Extracting from {zip_file.name}...")
        with zipfile.ZipFile(zip_file, 'r') as zip_ref:
            zip_ref.extractall(paths['openmesh_raw'])
        print("✓ Extracted")
        
        ds_links, links_meta = load_openmesh_cml(links_file, links_meta_file)
        pws_data = load_pws_from_netcdf(pws_file)
        print(f"✓ Links: {len(ds_links.cml_id)} links")
        print(f"✓ PWS: {len(pws_data)} stations")
        return ds_links, links_meta, pws_data
    
    # Step 3: Need to download
    print("⚠ NetCDF files not found")
    print("\n💡 To get OpenMesh data:")
    print("  Option 1: Download openmesh_data.zip")
    print(f"    Save as: {zip_file}")
    print("    Re-run this cell")
    print("\n  Option 2: Place NetCDF files directly in:")
    print(f"    {links_file}")
    print(f"    {pws_file}")
    
    return None, None, {}


def load_or_fetch_openmesh(
        paths: Optional[Dict[str, Path]] = None,
        mode: str = 'load',
        pws_source: str = 'sample'
) -> Tuple[Optional[xr.Dataset], Optional[pd.DataFrame], Dict[str, xr.Dataset]]:
    """
    Load OpenMesh data; if mode is 'fetch' and files are missing, download them first.

    Parameters
    ----------
    paths : dict, optional
        Paths from get_default_paths(). If None, uses get_default_paths().
    mode : str, 'load' or 'fetch'
        'load': only load from disk.
        'fetch': if files missing, download first, then load.
    pws_source : str, 'sample' or 'full'
        'sample' = pws_opensense_sample_jan.nc
        'full' = pws_wu_os.nc

    Returns
    -------
    ds_links : xr.Dataset or None
    links_meta : pd.DataFrame or None
    pws_data : dict of station_id -> xr.Dataset
    """
    if paths is None:
        paths = get_default_paths()

    raw = paths['openmesh_raw']
    cml_file = raw / 'ds_openmesh.nc'
    pws_filename = 'pws_opensense_sample_jan.nc' if pws_source.lower() == 'sample' else 'pws_wu_os.nc'
    pws_file = raw / pws_filename
    links_meta_file = _first_existing([
        paths['openmesh_meta'] / 'links_metadata.csv',
        paths['meta'] / 'links_metadata.csv',
        paths.get('links', paths['meta']) / 'links_metadata.csv',
    ]) or (paths['openmesh_meta'] / 'links_metadata.csv')

    # Check what exists
    cml_exists = cml_file.exists()
    pws_exists = pws_file.exists()

    print("=" * 70)
    print("OPENMESH DATA")
    print("=" * 70)

    # Determine actual action
    if mode.lower() == 'fetch':
        if cml_exists and pws_exists:
            print(f"Mode: fetch → files exist, loading instead")
        elif not cml_exists or not pws_exists:
            missing = []
            if not cml_exists:
                missing.append('links')
            if not pws_exists:
                missing.append('PWS')
            print(f"Mode: fetch → downloading {', '.join(missing)}...")
    else:
        print(f"Mode: load")

    # Show files being loaded
    print(f"  Links: {cml_file.name}")
    print(f"  PWS ({pws_source}): {pws_filename}")

    # Handle load-only mode
    if mode.lower() == 'load':
        if not cml_exists or not pws_exists:
            missing = []
            if not cml_exists:
                missing.append(cml_file.name)
            if not pws_exists:
                missing.append(pws_filename)
            print(f"✗ Missing: {', '.join(missing)}")
            print("  Use mode='fetch' to download")
            print("=" * 70)
            return None, None, {}

        ds_links, links_meta = load_openmesh_cml(cml_file, links_meta_file, verbose=False)
        pws_data = load_pws_from_netcdf(file_type=pws_source, verbose=False)

        print(f"✓ Links: {len(ds_links.cml_id)} | PWS: {len(pws_data)} stations")
        print("=" * 70)
        return ds_links, links_meta, pws_data

    # mode == 'fetch'
    need_cml = not cml_exists
    need_pws_sample = (pws_source.lower() == 'sample') and (not pws_exists)
    need_pws_full = (pws_source.lower() == 'full') and (not pws_exists)

    # Check if fetch functions available
    if _run_openmesh_pipeline is None or _run_pws_wu_pipeline is None:
        if need_cml or need_pws_sample or need_pws_full:
            print("✗ fetch_data module not available, cannot download")
            print("=" * 70)
            return None, None, {}

    # Fetch if needed
    if need_cml or need_pws_sample:
        _run_openmesh_pipeline(verbose=False)
    if need_pws_full:
        _run_pws_wu_pipeline()

    # Verify and load
    if not cml_file.exists():
        print("✗ Links file missing after fetch")
        print("=" * 70)
        return None, None, {}

    ds_links, links_meta = load_openmesh_cml(cml_file, links_meta_file)
    pws_data = load_pws_from_netcdf(file_type=pws_source)

    if not pws_data and not pws_file.exists():
        print("✗ PWS file missing after fetch")

    if ds_links is not None and pws_data:
        print(f"✓ Links: {len(ds_links.cml_id)} | PWS: {len(pws_data)} stations")
    print("=" * 70)

    return ds_links, links_meta, pws_data


# ============================================================================
# LOAD OR FETCH DATA (Unified function)
# ============================================================================

def load_or_fetch_data(
    mode: str,
    start_date: datetime,
    end_date: datetime,
    acquire_asos: bool = True,
    acquire_wu: bool = True,
    asos_stations: Optional[List[str]] = None,
    wu_stations: Optional[List[str]] = None,
    asos_metadata: Optional[pd.DataFrame] = None,
    wu_metadata: Optional[pd.DataFrame] = None,
    paths: Optional[Dict[str, Path]] = None
) -> Dict[str, Any]:
    """Load data from files or fetch from APIs."""
    if paths is None:
        paths = get_default_paths()
    
    print("=" * 70)
    print(f"DATA ACQUISITION: {mode.upper()}")
    print(f"Period: {start_date.date()} → {end_date.date()}")
    print("=" * 70)
    
    result = {
        'asos': {},
        'wu': {},
        'info': {'mode': mode, 'period': (start_date, end_date)}
    }
    
    if mode == 'fetch':
        # FETCH MODE
        if acquire_asos:
            stations_to_fetch = asos_stations
            
            if not stations_to_fetch and asos_metadata is not None and not asos_metadata.empty:
                # Handle both column name variations
                if 'Station ID' in asos_metadata.columns:
                    stations_to_fetch = asos_metadata['Station ID'].tolist()
                elif 'station_id' in asos_metadata.columns:
                    stations_to_fetch = asos_metadata['station_id'].tolist()
                else:
                    print(f"\n⚠ ASOS: No 'Station ID' or 'station_id' column found in metadata")
                    stations_to_fetch = []
                if stations_to_fetch:
                    print(f"\n📡 ASOS: Fetching ALL from metadata ({len(stations_to_fetch)} stations)")
            elif stations_to_fetch:
                print(f"\n📡 ASOS: Fetching {len(stations_to_fetch)} specified stations")
            else:
                print(f"\n⚠ ASOS: No stations or metadata provided")
            
            if stations_to_fetch:
                asos_data, _ = fetch_asos_data(stations_to_fetch, start_date, end_date)
                result['asos'] = asos_data if asos_data else {}
                result['info']['asos_file'] = 'API fetch'
        
        if acquire_wu:
            stations_to_fetch = wu_stations
            
            if not stations_to_fetch and wu_metadata is not None and not wu_metadata.empty:
                # Handle both column name variations
                if 'Station ID' in wu_metadata.columns:
                    stations_to_fetch = wu_metadata['Station ID'].tolist()
                elif 'station_id' in wu_metadata.columns:
                    stations_to_fetch = wu_metadata['station_id'].tolist()
                else:
                    print(f"\n⚠ WU: No 'Station ID' or 'station_id' column found in metadata")
                    stations_to_fetch = []
                if stations_to_fetch:
                    print(f"\n📡 WU: Fetching ALL from metadata ({len(stations_to_fetch)} stations)")
            elif stations_to_fetch:
                print(f"\n📡 WU: Fetching {len(stations_to_fetch)} specified stations")
            else:
                print(f"\n⚠ WU: No stations or metadata provided")
            
            if stations_to_fetch:
                wu_api_key = get_api_key()
                if wu_api_key:
                    wu_data, _ = fetch_wu_data(stations_to_fetch, start_date, end_date, units='m')
                    result['wu'] = wu_data if wu_data else {}
                    result['info']['wu_file'] = 'API fetch'
                else:
                    print(f"  ⚠ No API key - cannot fetch")
    
    elif mode == 'load':
        # LOAD MODE
        target_key = f"{start_date.strftime('%Y-%m-%d')}_{end_date.strftime('%Y-%m-%d')}"
        
        if acquire_asos:
            print(f"\n📁 ASOS")
            print(f"  Folder: {paths['asos']}")
            
            from fetch_data.noaa_asos.asos_fetch import load_all_data
            all_asos = load_all_data(paths['asos'], prefix='standard', verbose=False)
            
            if all_asos:
                available = list(all_asos.keys())
                print(f"  Available files ({len(available)}):")
                for key in available[:3]:
                    print(f"    - standard_{key}.csv")
                if len(available) > 3:
                    print(f"    ... +{len(available)-3} more")
                
                if target_key in all_asos:
                    selected = target_key
                    print(f"  ✓ Exact match: standard_{selected}.csv")
                else:
                    # Find best match based on both start and end dates, and number of stations
                    def date_match_score(key):
                        try:
                            file_start_str, file_end_str = key.split('_')
                            file_start = datetime.strptime(file_start_str, '%Y-%m-%d')
                            file_end = datetime.strptime(file_end_str, '%Y-%m-%d')
                            
                            # Calculate total difference (start date diff + end date diff)
                            start_diff = abs((file_start - start_date).days)
                            end_diff = abs((file_end - end_date).days)
                            total_diff = start_diff + end_diff
                            
                            return total_diff
                        except:
                            return 999999  # Invalid date format
                    
                    # Sort by match score, then by number of stations (more is better)
                    scored = [(key, date_match_score(key), len(all_asos[key])) 
                             for key in available]
                    scored.sort(key=lambda x: (x[1], -x[2]))  # Sort by score (asc), then by stations (desc)
                    
                    selected = scored[0][0]
                    best_score = scored[0][1]
                    best_stations = scored[0][2]
                    
                    print(f"  ⚠ No exact match for {target_key}")
                    print(f"  ✓ Using best match: standard_{selected}.csv")
                    print(f"    Date difference: {best_score} days, Stations: {best_stations}")
                    if len(scored) > 1:
                        print(f"    (Also considered {len(scored)-1} other file(s))")
                
                result['asos'] = all_asos[selected]
                result['info']['asos_file'] = f"standard_{selected}.csv"
            else:
                print(f"  ✗ No files found")
        
        if acquire_wu:
            print(f"\n📁 WU")
            print(f"  Folder: {paths['wu']}")
            
            wu_data, wu_file = load_wu_from_files(paths['wu'], start_date=start_date, end_date=end_date)
            if wu_data:
                print(f"  ✓ File: WU_{wu_file}.csv")
                result['wu'] = wu_data
                result['info']['wu_file'] = f"WU_{wu_file}.csv"
            else:
                print(f"  ✗ No files found")
    
    else:
        print(f"\n✗ Invalid mode: '{mode}'")
    
    print("\n" + "=" * 70)
    print(f"✓ ASOS: {len(result['asos'])} stations")
    print(f"✓ WU: {len(result['wu'])} stations")
    print("=" * 70)
    
    return result


# ============================================================================
# DYNAMIC PARAMETER DISCOVERY
# ============================================================================

def discover_available_parameters(
    data: Union[Dict[str, pd.DataFrame], Dict[str, xr.Dataset]],
    source_type: str = 'dataframe'
) -> Dict[str, str]:
    """
    Discover all available parameters in a dataset.
    
    Returns
    -------
    {original_column_name: standardized_name}  # WITHOUT units in keys
    """
    all_columns = set()
    
    if source_type == 'dataframe':
        for df in data.values():
            if isinstance(df, pd.DataFrame):
                all_columns.update(df.columns)
    elif source_type == 'netcdf':
        for ds in data.values():
            if hasattr(ds, 'data_vars'):
                all_columns.update(ds.data_vars)
    
    # Remove metadata columns
    exclude = {'datetime', 'station_id', 'station', 'time', 'id', 'lat', 'lon', 'elev'}
    all_columns = all_columns - exclude
    
    # Create standardized names (NO UNITS)
    standardized = {}
    for col in all_columns:
        col_lower = col.lower()
        
        # Rainfall/precipitation
        # CRITICAL: Exclude category/type columns (they're not numeric data)
        if any(x in col_lower for x in ['precip', 'rain']) and 'categor' not in col_lower and 'type' not in col_lower:
            if 'rate' in col_lower:
                standardized[col] = 'rainfall_rate'
            else:
                standardized[col] = 'rainfall_amount'
                # DIAGNOSTIC: Print mapping for rainfall
                print(f"  🔍 Parameter mapping: '{col}' → '{standardized[col]}'")
        
        # Temperature
        elif ('temp' in col_lower and 'dew' not in col_lower and 'dewpoint' not in col_lower) or \
             col_lower in ['t', 't2m', 't_air', 'air_temperature', 'air_temp']:
            standardized[col] = 'temperature'
        
        # Dewpoint
        elif 'dew' in col_lower or 'dwp' in col_lower:
            standardized[col] = 'dewpoint'
        
        # Humidity
        elif 'hum' in col_lower or 'relh' in col_lower or col_lower == 'rh':
            standardized[col] = 'humidity'
        
        # Pressure
        elif 'pres' in col_lower or 'alti' in col_lower:
            standardized[col] = 'pressure'
        
        # Wind speed/velocity
        elif 'wind' in col_lower and ('speed' in col_lower or 'velocity' in col_lower or col_lower == 'sknt'):
            standardized[col] = 'wind_speed'
        
        # Wind direction
        elif 'wind' in col_lower and ('dir' in col_lower or col_lower == 'drct'):
            standardized[col] = 'wind_direction'
        
        # Solar radiation
        elif 'solar' in col_lower or col_lower == 'srad':
            standardized[col] = 'solar_radiation'
        
        # Visibility
        elif 'vis' in col_lower:
            standardized[col] = 'visibility'
        
        # Cloud cover
        elif 'cloud' in col_lower or 'skyc' in col_lower:
            standardized[col] = 'cloud_cover'
        
        # Unknown - keep original
        else:
            standardized[col] = col
    
    return standardized


# ============================================================================
# UNIT CONVERSION
# ============================================================================

def fahrenheit_to_celsius(f):
    return (f - 32) * 5/9

def knots_to_ms(knots):
    return knots * 0.514444

def inhg_to_hpa(inhg):
    return inhg * 33.8639

def apply_unit_conversion(df: pd.DataFrame, param_name: str, source: str, original_col: str = None) -> pd.DataFrame:
    """Apply unit conversion based on parameter and source.
    
    Parameters
    ----------
    df : pd.DataFrame
        DataFrame to convert
    param_name : str
        Standardized parameter name (e.g., 'temperature')
    source : str
        Data source ('asos', 'wu', etc.)
    original_col : str, optional
        Original column name before standardization. If 'temperature' or 'dewpoint',
        data is already in Celsius (from standard CSV). If 'tmpf' or 'dwpf', needs conversion.
    """
    df = df.copy()
    
    # ASOS conversions
    # NOTE: Standard CSV files from asos_fetch.py already have temperature/dewpoint in Celsius
    # The column name 'temperature' means it's already converted, 'tmpf' means it needs conversion
    if source == 'asos':
        for col in df.columns:
            if param_name in ['temperature', 'dewpoint']:
                # Check original column name to determine if conversion is needed
                # If original_col is 'temperature' or 'dewpoint', it's already in Celsius (from standard CSV)
                # If original_col is 'tmpf' or 'dwpf', it's in Fahrenheit and needs conversion
                if original_col and original_col.lower() in ['tmpf', 'dwpf']:
                    # Raw Fahrenheit data - convert to Celsius
                    df[col] = df[col].apply(lambda x: fahrenheit_to_celsius(x) if pd.notna(x) else np.nan)
                # Otherwise, assume already in Celsius (from standard CSV files) - DO NOT CONVERT
            elif param_name == 'wind_speed':
                # Convert knots to m/s, handling NaN
                df[col] = df[col].apply(lambda x: knots_to_ms(x) if pd.notna(x) else np.nan)
            elif param_name == 'pressure':
                # Convert inHg to hPa, handling NaN
                df[col] = df[col].apply(lambda x: inhg_to_hpa(x) if pd.notna(x) else np.nan)
            # Note: rainfall parameters (rainfall_amount, rainfall_rate) don't need conversion
            # They're already in mm/mm per hour from standard CSV files
    
    return df


# ============================================================================
# PARAMETER EXTRACTION
# ============================================================================

def extract_parameter_from_dataframes(
        data: Dict[str, pd.DataFrame],
        original_col: str,
        standard_name: str,
        source: str,
        common_start: datetime,
        common_end: datetime
) -> pd.DataFrame:
    """Extract a parameter from DataFrame-based data (ASOS, WU) - Clean Version."""
    param_list = []

    for station_id, df in data.items():
        # Check if required columns exist
        if original_col not in df.columns or 'datetime' not in df.columns:
            continue

        # Check for numeric vs categorical (e.g., precip_type)
        is_categorical = (
                'type' in original_col.lower() or
                'category' in original_col.lower() or
                'categor' in original_col.lower()
        )

        # 1. Basic Cleaning & Type Checking
        if 'rainfall' in standard_name and not is_categorical:
            # Skip object columns that aren't convertible to numbers
            col_dtype = df[original_col].dtype
            sample_val = df[original_col].iloc[0] if len(df) > 0 else None
            if col_dtype == 'object' and not isinstance(sample_val, (int, float)):
                try:
                    pd.to_numeric(df[original_col].head(10), errors='raise')
                except (ValueError, TypeError):
                    continue

        df_station = df[['datetime', original_col]].copy()

        # 2. Datetime Parsing
        if not pd.api.types.is_datetime64_any_dtype(df_station['datetime']):
            df_station['datetime'] = pd.to_datetime(df_station['datetime'], errors='coerce')

        df_station = df_station[df_station['datetime'].notna()]

        # 3. Numeric Conversion (if not categorical)
        if not is_categorical:
            if df_station[original_col].dtype == 'object':
                missing_indicators = ['NP', 'M', '-', '', 'nan', 'NaN', 'NULL', 'null']
                df_station[original_col] = df_station[original_col].replace(missing_indicators, np.nan)

            df_station[original_col] = pd.to_numeric(df_station[original_col], errors='coerce')

        # 4. Unit Conversion (if not categorical)
        # Note: 'rainfall' checks usually handled inside apply_unit_conversion or skipped here if needed
        if not is_categorical:
            try:
                df_station[original_col] = apply_unit_conversion(
                    df_station[[original_col]], standard_name, source, original_col=original_col
                )[original_col]
            except NameError:
                pass  # Safety if helper not defined in this scope

        # 5. Date Filtering (Handle Timezone Awareness)
        mask = df_station['datetime'].notna()
        if mask.any():
            is_tz_aware = pd.api.types.is_datetime64tz_dtype(df_station['datetime'])
            common_start_clean = common_start
            common_end_clean = common_end

            if is_tz_aware:
                # Match timezone of data
                first_valid = df_station['datetime'].iloc[df_station['datetime'].notna().idxmax()]
                if hasattr(first_valid, 'tz'):
                    tz = first_valid.tz
                    if tz is not None:
                        if common_start.tzinfo is None: common_start_clean = common_start.replace(tzinfo=tz)
                        if common_end.tzinfo is None: common_end_clean = common_end.replace(tzinfo=tz)
            else:
                # Force naive if data is naive
                if common_start.tzinfo is not None: common_start_clean = common_start.replace(tzinfo=None)
                if common_end.tzinfo is not None: common_end_clean = common_end.replace(tzinfo=None)

            mask = mask & (df_station['datetime'] >= common_start_clean) & (df_station['datetime'] <= common_end_clean)

        df_station = df_station[mask]

        # 6. Store Result
        if len(df_station) > 0:
            df_station.set_index('datetime', inplace=True)
            df_station.columns = [station_id]
            param_list.append(df_station)

    # 7. Combine & Finalize
    if param_list:
        df_combined = pd.concat(param_list, axis=1, sort=True)

        is_categorical_param = (
                'type' in standard_name.lower() or
                'category' in standard_name.lower() or
                'categor' in standard_name.lower()
        )

        if 'rainfall' in standard_name and not is_categorical_param:
            df_combined = df_combined.fillna(0)

        return df_combined

    return pd.DataFrame()

def extract_parameter_from_netcdf(
    pws_data: Dict[str, xr.Dataset],
    original_var: str,
    standard_name: str,
    common_start: datetime,
    common_end: datetime,
    station_ids: Optional[list] = None
) -> pd.DataFrame:
    """Extract a parameter from NetCDF-based PWS data."""
    if station_ids is None:
        station_ids = list(pws_data.keys())
    
    station_dfs = {}
    
    for station_id in station_ids:
        if station_id not in pws_data:
            continue
        
        try:
            station_ds = pws_data[station_id]
            
            if original_var not in station_ds.data_vars:
                continue
            
            # Extract time
            time_values = station_ds.time.values
            if np.issubdtype(time_values.dtype, np.integer):
                time_index = pd.to_datetime(time_values, unit='s', errors='coerce')
            else:
                time_index = pd.to_datetime(time_values, errors='coerce')
            
            # Extract values
            values = station_ds[original_var].values
            
            if values.ndim > 1:
                values = values.flatten()
            
            if len(values) != len(time_index):
                min_len = min(len(values), len(time_index))
                values = values[:min_len]
                time_index = time_index[:min_len]
            
            df_station = pd.DataFrame({station_id: values}, index=time_index)
            df_station = df_station[df_station.index.notna()]
            
            # Filter to analysis period
            df_station = df_station[
                (df_station.index >= common_start) & 
                (df_station.index <= common_end)
            ]
            
            if len(df_station) > 0:
                station_dfs[station_id] = df_station
            
        except Exception:
            continue
    
    if len(station_dfs) == 0:
        return pd.DataFrame()
    
    # Combine all stations
    df_all = pd.DataFrame()
    for station_id, df_station in station_dfs.items():
        if len(df_all) == 0:
            df_all = df_station.copy()
        else:
            df_all = df_all.join(df_station, how='outer')
    
    df_all = df_all.sort_index()
    
    if 'rainfall' in standard_name:
        df_all = df_all.fillna(0).clip(lower=0, upper=20)
    
    return df_all


# ============================================================================
# MAIN ANALYSIS DATA PREPARATION (DYNAMIC)
# ============================================================================


# ============================================================================
# BACKWARD COMPATIBILITY
# ============================================================================

def extract_pws_rainfall(pws_data: Dict[str, xr.Dataset], station_id: str) -> pd.DataFrame:
    """Extract rainfall from single PWS station."""
    if station_id not in pws_data:
        raise ValueError(f"Station '{station_id}' not found")
    
    df = extract_parameter_from_netcdf(
        pws_data, 'rainfall_amount', 'rainfall_amount',
        datetime(1970, 1, 1), datetime(2100, 1, 1), [station_id]
    )
    
    if df.empty:
        df = extract_parameter_from_netcdf(
            pws_data, 'rainfall_rate', 'rainfall_rate',
            datetime(1970, 1, 1), datetime(2100, 1, 1), [station_id]
        )
        if not df.empty:
            df = df * (5/60)
    
    if not df.empty:
        df.columns = ['precipitation_mm']
    
    return df


def extract_all_pws_rainfall(pws_data: Dict[str, xr.Dataset], station_ids: Optional[list] = None) -> pd.DataFrame:
    """Extract rainfall from all PWS stations."""
    df = extract_parameter_from_netcdf(
        pws_data, 'rainfall_amount', 'rainfall_amount',
        datetime(1970, 1, 1), datetime(2100, 1, 1), station_ids
    )
    
    if df.empty:
        df = extract_parameter_from_netcdf(
            pws_data, 'rainfall_rate', 'rainfall_rate',
            datetime(1970, 1, 1), datetime(2100, 1, 1), station_ids
        )
        if not df.empty:
            df = df * (5/60)
    
    return df

    


def display_sensors_map(links_meta=None, pws_meta=None, asos_meta=None, 
                    link_pws_matches=None, 
                    cml_ids=None,                    # NEW: filter by CML IDs
                    pws_station_ids=None,            # Already exists
                    asos_station_ids=None,           # Already exists
                    center_lat=None, center_lon=None,
                    map_type='folium', figsize=(14, 10),
                    show_link_labels=True):
    """
    Create a map showing selected sensors from metadata.
    
    Parameters
    ----------
    links_meta : DataFrame, optional
        Links metadata
    pws_meta : DataFrame, optional
        PWS metadata
    asos_meta : DataFrame, optional
        ASOS metadata
    link_pws_matches : DataFrame, optional
        Matched links to PWS (from match_links_to_pws)
    cml_ids : list, optional
        List of CML IDs to show (None = show all)
        Example: ['1', '2', '5']
    pws_station_ids : list, optional
        List of PWS station IDs to show (None = show all)
    asos_station_ids : list, optional
        List of ASOS station IDs to show (None = show all)
    center_lat, center_lon : float, optional
        Map center coordinates. If None, calculates from data.
    map_type : str
        'folium' = interactive folium map (default)
        'matplotlib' = static matplotlib map with coordinates
    figsize : tuple
        Figure size for matplotlib map (default: (14, 10))
    show_link_labels : bool
        Whether to show CML link labels (default: True)
    
    Returns
    -------
    map_obj : folium.Map or (fig, ax)
        Interactive map object (folium) or matplotlib figure and axes
    
    Examples
    --------
    >>> # Show all sensors
    >>> m = map_all_sensors(links_meta, pws_meta, asos_meta)
    
    >>> # Show only specific CMLs and PWS stations
    >>> m = map_all_sensors(links_meta, pws_meta, 
    ...                     cml_ids=['1', '2', '5'],
    ...                     pws_station_ids=['KNYNEWYO1805', 'KNYNEWYO2010'])
    
    >>> # Static matplotlib map
    >>> fig, ax = map_all_sensors(links_meta, pws_meta, 
    ...                           cml_ids=['10', '20'],
    ...                           map_type='matplotlib')
    """
    # Filter links by cml_ids if provided
    if links_meta is not None and not links_meta.empty and cml_ids is not None:
        links_meta = links_meta[links_meta['cml_id'].isin(cml_ids)].copy()
        if len(links_meta) == 0:
            print(f"⚠ No CML links found matching: {cml_ids}")
        else:
            print(f"✓ Filtered to {len(links_meta)} CML links")
    
    # Filter PWS by station_ids if provided
    if pws_meta is not None and not pws_meta.empty and pws_station_ids is not None:
        if 'Station ID' in pws_meta.columns:
            pws_meta = pws_meta[pws_meta['Station ID'].isin(pws_station_ids)].copy()
        elif 'station_id' in pws_meta.columns:
            pws_meta = pws_meta[pws_meta['station_id'].isin(pws_station_ids)].copy()
        
        if len(pws_meta) == 0:
            print(f"⚠ No PWS stations found matching: {pws_station_ids}")
        else:
            print(f"✓ Filtered to {len(pws_meta)} PWS stations")
    
    # Filter ASOS by station_ids if provided
    if asos_meta is not None and not asos_meta.empty and asos_station_ids is not None:
        if 'Station ID' in asos_meta.columns:
            asos_meta = asos_meta[asos_meta['Station ID'].isin(asos_station_ids)].copy()
        elif 'station_id' in asos_meta.columns:
            asos_meta = asos_meta[asos_meta['station_id'].isin(asos_station_ids)].copy()
        
        if len(asos_meta) == 0:
            print(f"⚠ No ASOS stations found matching: {asos_station_ids}")
        else:
            print(f"✓ Filtered to {len(asos_meta)} ASOS stations")
    
    # Determine map center
    all_lats = []
    all_lons = []
    
    if links_meta is not None and not links_meta.empty:
        all_lats.extend([links_meta['site_0_lat'].values, links_meta['site_1_lat'].values])
        all_lons.extend([links_meta['site_0_lon'].values, links_meta['site_1_lon'].values])
    
    if pws_meta is not None and not pws_meta.empty:
        if 'Latitude' in pws_meta.columns:
            all_lats.append(pws_meta['Latitude'].values)
            all_lons.append(pws_meta['Longitude'].values)
        elif 'lat' in pws_meta.columns:
            all_lats.append(pws_meta['lat'].values)
            all_lons.append(pws_meta['lon'].values)
    
    if asos_meta is not None and not asos_meta.empty:
        if 'Latitude' in asos_meta.columns:
            all_lats.append(asos_meta['Latitude'].values)
            all_lons.append(asos_meta['Longitude'].values)
        elif 'lat' in asos_meta.columns:
            all_lats.append(asos_meta['lat'].values)
            all_lons.append(asos_meta['lon'].values)
    
    if all_lats:
        all_lats = np.concatenate([np.array(x).flatten() for x in all_lats if len(x) > 0])
        all_lons = np.concatenate([np.array(x).flatten() for x in all_lons if len(x) > 0])
        center_lat = center_lat if center_lat else np.mean(all_lats)
        center_lon = center_lon if center_lon else np.mean(all_lons)
        lat_range = (all_lats.min(), all_lats.max())
        lon_range = (all_lons.min(), all_lons.max())
    else:
        center_lat = center_lat if center_lat else 40.7
        center_lon = center_lon if center_lon else -73.9
        lat_range = (center_lat - 0.1, center_lat + 0.1)
        lon_range = (center_lon - 0.1, center_lon + 0.1)
    
    # Choose map type
    if map_type == 'matplotlib':
        return _create_matplotlib_map(
            links_meta, pws_meta, asos_meta, link_pws_matches,
            center_lat, center_lon, lat_range, lon_range, figsize,
            pws_station_ids=None,  # Already filtered above
            asos_station_ids=None,  # Already filtered above
            show_link_labels=show_link_labels
        )
    
    # Create folium map
    m = folium.Map(location=[center_lat, center_lon], zoom_start=12, tiles='OpenStreetMap')
    
    # Add links
    if links_meta is not None and not links_meta.empty:
        links_group = folium.FeatureGroup(name='CML Links')
        for idx, link in links_meta.iterrows():
            lat0, lon0 = link['site_0_lat'], link['site_0_lon']
            lat1, lon1 = link['site_1_lat'], link['site_1_lon']
            cml_id = link['cml_id']
            sublink_id = link.get('sublink_id', '')
            
            # Draw link line
            folium.PolyLine(
                locations=[[lat0, lon0], [lat1, lon1]],
                color='blue',
                weight=2,
                opacity=0.6,
                popup=f'CML {cml_id} - {sublink_id}'
            ).add_to(links_group)
            
            # Add markers for endpoints
            folium.CircleMarker(
                location=[lat0, lon0],
                radius=3,
                color='blue',
                fill=True,
                popup=f'CML {cml_id} Site 0'
            ).add_to(links_group)
            
            folium.CircleMarker(
                location=[lat1, lon1],
                radius=3,
                color='blue',
                fill=True,
                popup=f'CML {cml_id} Site 1'
            ).add_to(links_group)
        
        links_group.add_to(m)
    
    # Add PWS stations
    if pws_meta is not None and not pws_meta.empty:
        pws_group = folium.FeatureGroup(name='PWS Stations')
        for idx, pws in pws_meta.iterrows():
            if 'Latitude' in pws_meta.columns:
                lat, lon = pws['Latitude'], pws['Longitude']
                station_id = pws.get('Station ID', f'PWS_{idx}')
            else:
                lat, lon = pws['lat'], pws['lon']
                station_id = pws.get('station_id', f'PWS_{idx}')
            
            folium.CircleMarker(
                location=[lat, lon],
                radius=5,
                color='green',
                fill=True,
                fillColor='green',
                popup=f'PWS: {station_id}'
            ).add_to(pws_group)
        
        pws_group.add_to(m)
    
    # Add ASOS stations
    if asos_meta is not None and not asos_meta.empty:
        asos_group = folium.FeatureGroup(name='ASOS Stations')
        for idx, asos in asos_meta.iterrows():
            if 'Latitude' in asos_meta.columns:
                lat, lon = asos['Latitude'], asos['Longitude']
                station_id = asos.get('Station ID', f'ASOS_{idx}')
            else:
                lat, lon = asos['lat'], asos['lon']
                station_id = asos.get('station_id', f'ASOS_{idx}')
            
            folium.CircleMarker(
                location=[lat, lon],
                radius=6,
                color='red',
                fill=True,
                fillColor='red',
                popup=f'ASOS: {station_id}'
            ).add_to(asos_group)
        
        asos_group.add_to(m)
    
    # Add matched links to PWS connections
    if link_pws_matches is not None and not link_pws_matches.empty:
        # Filter matches if we filtered links or pws
        if cml_ids is not None:
            link_pws_matches = link_pws_matches[link_pws_matches['cml_id'].isin(cml_ids)]
        if pws_station_ids is not None:
            link_pws_matches = link_pws_matches[link_pws_matches['pws_station_id'].isin(pws_station_ids)]
        
        if not link_pws_matches.empty:
            matches_group = folium.FeatureGroup(name='Link-PWS Matches')
            for idx, match in link_pws_matches.iterrows():
                folium.PolyLine(
                    locations=[[match['link_mid_lat'], match['link_mid_lon']],
                              [match['pws_lat'], match['pws_lon']]],
                    color='orange',
                    weight=2,
                    opacity=0.5,
                    dashArray='5, 5',
                    popup=f"CML {match['cml_id']} ↔ {match['pws_station_id']} ({match['distance_km']:.2f} km)"
                ).add_to(matches_group)
            
            matches_group.add_to(m)
    
    # Add layer control
    folium.LayerControl().add_to(m)
    
    print("✓ Map created")
    return m


# ============================================================================
# CELL 6: Quick Data Exploration - Modular Plotting Functions
# ============================================================================

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np


def handle_outliers(df, method='clip', percentile=(1, 99)):
    """
    Handle outliers in dataframe.
    
    Parameters
    ----------
    df : DataFrame
        Data to process
    method : str
        'clip' = clip to percentile bounds
        'remove' = set outliers to NaN
        'none' = no handling
    percentile : tuple
        (lower, upper) percentiles for clipping
    
    Returns
    -------
    DataFrame with outliers handled
    """
    if method == 'none':
        return df
    
    df_clean = df.copy()
    
    # Only process numeric columns
    numeric_cols = df_clean.select_dtypes(include=[np.number]).columns
    
    for col in numeric_cols:
        try:
            # Ensure column is numeric
            if not pd.api.types.is_numeric_dtype(df_clean[col]):
                continue
            
            # Skip if all values are NaN
            if df_clean[col].isna().all():
                continue
            
            # Calculate quantiles
            lower = df_clean[col].quantile(percentile[0] / 100)
            upper = df_clean[col].quantile(percentile[1] / 100)
            
            # Skip if quantiles are invalid
            if pd.isna(lower) or pd.isna(upper):
                continue
            
            if method == 'clip':
                df_clean[col] = df_clean[col].clip(lower=lower, upper=upper)
            elif method == 'remove':
                df_clean.loc[(df_clean[col] < lower) | (df_clean[col] > upper), col] = np.nan
        except (TypeError, ValueError) as e:
            # Skip columns that can't be processed (e.g., string columns)
            continue
    
    return df_clean


def plot_all_stations(ax, df, param_name, max_stations=10, alpha=0.7, linewidth=1.5):
    """Plot all individual stations."""
    stations_to_plot = df.columns[:max_stations]
    for station in stations_to_plot:
        ax.plot(df.index, df[station], alpha=alpha, label=station, linewidth=linewidth)
    if len(stations_to_plot) > 0:
        ax.legend(loc='upper right', fontsize=10, ncol=min(2, len(stations_to_plot)))


def plot_statistics(ax, df, alpha=0.7, linewidth=2.5):
    """Plot mean, median, and min-max range."""
    mean_vals = df.mean(axis=1)
    median_vals = df.median(axis=1)
    min_vals = df.min(axis=1)
    max_vals = df.max(axis=1)
    
    ax.plot(df.index, mean_vals, 'b-', linewidth=linewidth, label='Mean', alpha=alpha)
    ax.plot(df.index, median_vals, 'g-', linewidth=linewidth, label='Median', alpha=alpha)
    ax.fill_between(df.index, min_vals, max_vals, alpha=0.2, color='gray', label='Min-Max Range')
    ax.legend(loc='upper right', fontsize=11)


def plot_quick_comparison(
    analysis_data,
    parameter='rainfall_amount[mm]',
    mode='all',  # 'all' or 'stats'
    max_pws_stations=5,
    outlier_method='clip',  # 'clip', 'remove', 'none'
    outlier_percentile=(1, 99),
    ylim_asos=None,
    ylim_pws=None,
    figsize=(16, 10),
    start_date=None,
    end_date=None
):
    """
    Quick comparison plot for ASOS vs PWS data.
    
    Parameters
    ----------
    analysis_data : dict
        Output from prepare_analysis_data()
    parameter : str
        Parameter to plot (e.g., 'rainfall_amount[mm]', 'temperature[C]')
    mode : str
        'all' = plot individual stations
        'stats' = plot statistics (mean, median, min-max)
    max_pws_stations : int
        Max PWS stations to plot in 'all' mode
    outlier_method : str
        'clip', 'remove', or 'none'
    outlier_percentile : tuple
        (lower, upper) percentiles for outlier handling
    ylim_asos : tuple, optional
        (min, max) y-axis limits for ASOS plot
    ylim_pws : tuple, optional
        (min, max) y-axis limits for PWS plot
    figsize : tuple
        Figure size
    start_date, end_date : datetime, optional
        Date range to plot
    """
    
    # Show available parameters
    print("Available parameters:")
    print(f"  ASOS: {list(analysis_data['asos'].keys())}")
    print(f"  PWS: {list(analysis_data['pws'].keys())}")
    print(f"\nPlotting: {parameter}")
    
    # Check if parameter exists
    has_asos = parameter in analysis_data['asos']
    has_pws = parameter in analysis_data['pws']
    
    if not has_asos and not has_pws:
        print(f"⚠ Parameter '{parameter}' not found in ASOS or PWS data")
        return None, None
    
    # Determine number of subplots
    n_plots = sum([has_asos, has_pws])
    fig, axes = plt.subplots(n_plots, 1, figsize=figsize, sharex=True)
    
    if n_plots == 1:
        axes = [axes]
    
    plot_idx = 0
    param_label = parameter.replace('[mm]', '').replace('[C]', '').replace('_', ' ').title()
    
    # Plot ASOS
    if has_asos:
        ax = axes[plot_idx]
        df_asos = analysis_data['asos'][parameter].copy()
        
        # Filter date range
        if start_date:
            df_asos = df_asos[df_asos.index >= start_date]
        if end_date:
            df_asos = df_asos[df_asos.index <= end_date]
        
        # Handle outliers
        df_asos = handle_outliers(df_asos, method=outlier_method, percentile=outlier_percentile)
        
        # Plot
        if mode == 'all':
            plot_all_stations(ax, df_asos, param_label)
        elif mode == 'stats':
            plot_statistics(ax, df_asos)
        
        # Format
        ax.set_title(f'ASOS - {param_label} ({len(df_asos.columns)} stations)', 
                    fontsize=14, fontweight='bold')
        ax.set_ylabel(param_label, fontsize=12, fontweight='bold')
        ax.grid(True, alpha=0.3)
        
        if ylim_asos:
            ax.set_ylim(ylim_asos)
        
        plot_idx += 1
    
    # Plot PWS
    if has_pws:
        ax = axes[plot_idx]
        df_pws = analysis_data['pws'][parameter].copy()
        
        # Filter date range
        if start_date:
            df_pws = df_pws[df_pws.index >= start_date]
        if end_date:
            df_pws = df_pws[df_pws.index <= end_date]
        
        # Handle outliers
        df_pws = handle_outliers(df_pws, method=outlier_method, percentile=outlier_percentile)
        
        # Limit stations in 'all' mode
        if mode == 'all' and len(df_pws.columns) > max_pws_stations:
            df_pws = df_pws.iloc[:, :max_pws_stations]
        
        # Plot
        if mode == 'all':
            plot_all_stations(ax, df_pws, param_label, max_stations=max_pws_stations)
        elif mode == 'stats':
            plot_statistics(ax, df_pws)
        
        # Format
        station_count = len(df_pws.columns) if mode == 'all' else len(analysis_data['pws'][parameter].columns)
        title_suffix = f"({station_count} stations)" if mode == 'all' else f"({station_count} stations)"
        ax.set_title(f'PWS - {param_label} {title_suffix}', 
                    fontsize=14, fontweight='bold')
        ax.set_ylabel(param_label, fontsize=12, fontweight='bold')
        ax.grid(True, alpha=0.3)
        
        if ylim_pws:
            ax.set_ylim(ylim_pws)
        
        plot_idx += 1
    
    # Format x-axis (shared) - smart tick spacing to avoid overlap
    axes[-1].set_xlabel('Date', fontsize=12, fontweight='bold')
    
    # Determine appropriate tick interval based on date range
    if start_date and end_date:
        date_range = (end_date - start_date).total_seconds() / 3600  # hours
    else:
        # Use data range from available datasets
        date_range = None
        if has_asos and len(df_asos) > 0:
            date_range = (df_asos.index[-1] - df_asos.index[0]).total_seconds() / 3600
        elif has_pws and len(df_pws) > 0:
            date_range = (df_pws.index[-1] - df_pws.index[0]).total_seconds() / 3600
        
        if date_range is None:
            date_range = 24  # default
    
    # Adjust tick interval based on date range
    if date_range <= 24:  # <= 1 day
        major_interval = 2  # hours
        date_format = '%H:%M'
    elif date_range <= 72:  # <= 3 days
        major_interval = 6  # hours
        date_format = '%m/%d %H:%M'
    elif date_range <= 168:  # <= 1 week
        major_interval = 12  # hours
        date_format = '%m/%d %H:%M'
    elif date_range <= 720:  # <= 30 days
        major_interval = 1  # days
        date_format = '%m/%d'
    else:  # > 30 days
        major_interval = 7  # days
        date_format = '%m/%d'
    
    # Apply formatting
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter(date_format))
    
    if date_range <= 168:  # Use hour locator for short ranges
        axes[-1].xaxis.set_major_locator(mdates.HourLocator(interval=major_interval))
        if date_range <= 24:
            axes[-1].xaxis.set_minor_locator(mdates.HourLocator(interval=1))
    else:  # Use day locator for longer ranges
        axes[-1].xaxis.set_major_locator(mdates.DayLocator(interval=major_interval))
        axes[-1].xaxis.set_minor_locator(mdates.HourLocator(interval=6))
    
    # Rotate x-axis labels for better readability (only if needed)
    rotation_angle = 45 if date_range <= 168 else 0
    for ax in axes:
        ax.tick_params(axis='x', which='major', rotation=rotation_angle, labelsize=10)
        ax.tick_params(axis='y', labelsize=10)
        # Ensure labels don't overlap
        ax.tick_params(axis='x', which='minor', labelsize=8)
    
    # Auto-adjust layout to prevent label cutoff
    plt.tight_layout()
    
    # Additional adjustment if labels still overlap
    if date_range <= 168:
        fig.autofmt_xdate(rotation=rotation_angle, ha='right')
    
    return fig, axes


def plot_cml_rsl(ds_links, 
                 cml_ids=None, 
                 sublink_ids=None, 
                 date_range=None,
                 figsize=(14, 6),
                 title=None,
                 legend_loc='upper right'):
    """
    Plot RSL time series for selected CML links.
    
    Parameters
    ----------
    ds_links : xarray.Dataset
        Links dataset from load_links()
    cml_ids : list or str, optional
        CML IDs to plot. If None, plots first 3 links.
        Examples: ['1', '2', '3'] or '1'
    sublink_ids : list or str, optional
        Sublink IDs to plot. If None, plots all sublinks.
        Examples: ['sublink_1', 'sublink_2'] or 'sublink_1'
    date_range : tuple, optional
        (start_date, end_date) to filter time range.
        Examples: ('2023-11-01', '2023-11-07') or ('2024-01-01', '2024-01-31')
    figsize : tuple, default (14, 6)
        Figure size (width, height)
    title : str, optional
        Plot title. If None, auto-generates title.
    legend_loc : str, default 'upper right'
        Legend location. Options: 'upper right', 'upper left', 'lower right', 'lower left', 'best'
    
    Examples
    --------
    >>> # Plot first 3 links, all sublinks
    >>> plot_cml_rsl(ds_links)
    
    >>> # Plot specific link
    >>> plot_cml_rsl(ds_links, cml_ids='5', sublink_ids='sublink_1')
    
    >>> # Plot with date range
    >>> plot_cml_rsl(ds_links, cml_ids=['1', '2'], 
    ...              date_range=('2023-11-01', '2023-11-07'))
    
    >>> # Big figure with date range, legend lower left
    >>> plot_cml_rsl(ds_links, cml_ids=['1', '2', '3'], 
    ...              sublink_ids='sublink_1', 
    ...              date_range=('2024-01-01', '2024-01-15'),
    ...              figsize=(18, 10),
    ...              legend_loc='lower left')
    """

    
    # Convert single values to lists
    if cml_ids is None:
        cml_ids = ds_links.cml_id.values[:3]  # First 3 links
    elif isinstance(cml_ids, str):
        cml_ids = [cml_ids]
    
    if sublink_ids is None:
        sublink_ids = ds_links.sublink_id.values  # All sublinks
    elif isinstance(sublink_ids, str):
        sublink_ids = [sublink_ids]
    
    # Filter by date range if specified
    ds_plot = ds_links
    if date_range is not None:
        start_date, end_date = date_range
        ds_plot = ds_links.sel(time=slice(start_date, end_date))
        print(f"📅 Date range: {start_date} to {end_date}")
        print(f"   Timesteps: {len(ds_plot.time)}")
    
    # Create plot
    fig, ax = plt.subplots(figsize=figsize)
    
    colors = plt.cm.tab10.colors
    color_idx = 0
    plotted_count = 0
    skipped = []
    
    # Plot each combination
    for cml_id in cml_ids:
        for sublink_id in sublink_ids:
            # Get frequency first to check if sublink exists
            freq = float(ds_links['frequency'].sel(cml_id=cml_id, sublink_id=sublink_id).values)
            
            # Skip if frequency is NaN (sublink doesn't exist)
            if np.isnan(freq):
                skipped.append(f"Link {cml_id} - {sublink_id}")
                continue
            
            # Extract RSL series
            rsl = ds_plot['rsl'].sel(cml_id=cml_id, sublink_id=sublink_id)
            
            # Get link metadata
            length = float(ds_links['length'].sel(cml_id=cml_id).values)
            
            # Plot
            label = f"Link {cml_id} - {sublink_id} (L={length:.0f}m, f={freq/1000:.1f}GHz)"
            ax.plot(ds_plot['time'].values, rsl.values, 
                   color=colors[color_idx % len(colors)], 
                   label=label, alpha=0.7, linewidth=1.5)
            
            color_idx += 1
            plotted_count += 1
    
    # Print info about skipped sublinks
    if skipped:
        print(f"⚠ Skipped {len(skipped)} sublinks (no data):")
        for s in skipped:
            print(f"  - {s}")
    
    # Check if anything was plotted
    if plotted_count == 0:
        print("✗ No valid sublinks found to plot")
        plt.close()
        return
    
    # Format plot - BIGGER EVERYTHING
    ax.set_xlabel("Time", fontsize=16, fontweight='bold')
    ax.set_ylabel("RSL (dBm)", fontsize=16, fontweight='bold')
    
    if title is None:
        title = f"CML RSL Time Series ({plotted_count} sublinks)"
    ax.set_title(title, fontsize=18, fontweight='bold', pad=20)
    
    # BIGGER ticks
    ax.tick_params(axis='both', labelsize=14)
    
    # Fix date overlap - format x-axis dates
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    
    # Rotate dates to prevent overlap
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')
    
    # BIGGER legend INSIDE the plot
    ax.legend(loc=legend_loc, fontsize=13, framealpha=0.9)
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.show()
# Example usage:
# Option 1: Plot all stations


def _create_matplotlib_map(links_meta, pws_meta, asos_meta, link_pws_matches,
                           center_lat, center_lon, lat_range, lon_range, figsize,
                           pws_station_ids=None, asos_station_ids=None,
                           show_link_labels=True):
    """Create static matplotlib map with coordinates."""

    
    fig, ax = plt.subplots(figsize=figsize)
    
    # Set axis limits with padding
    lat_padding = (lat_range[1] - lat_range[0]) * 0.1
    lon_padding = (lon_range[1] - lon_range[0]) * 0.1
    
    ax.set_xlim(lon_range[0] - lon_padding, lon_range[1] + lon_padding)
    ax.set_ylim(lat_range[0] - lat_padding, lat_range[1] + lat_padding)
    
    # Add grid with coordinates
    ax.grid(True, alpha=0.3, linestyle='--', linewidth=0.5)
    ax.set_xlabel('Longitude (°)', fontsize=18, fontweight='bold')
    ax.set_ylabel('Latitude (°)', fontsize=18, fontweight='bold')
    ax.set_title('Sensor Locations Map', fontsize=20, fontweight='bold', pad=25)
    
    # Format tick labels to show coordinates - LARGER (2 decimal places)
    ax.tick_params(axis='both', which='major', labelsize=16, width=2, length=8)
    ax.tick_params(axis='both', which='minor', labelsize=14, length=5)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{x:.2f}°'))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{x:.2f}°'))
    
    # Add links
    if links_meta is not None and not links_meta.empty:
        for idx, link in links_meta.iterrows():
            lat0, lon0 = link['site_0_lat'], link['site_0_lon']
            lat1, lon1 = link['site_1_lat'], link['site_1_lon']
            cml_id = link['cml_id']
            sublink_id = link.get('sublink_id', '')
            
            # Draw link line
            ax.plot([lon0, lon1], [lat0, lat1], 'b-', linewidth=1.5, alpha=0.6, 
                   label='CML Links' if idx == 0 else '')
            
            # Add markers for endpoints
            ax.plot(lon0, lat0, 'bo', markersize=4, alpha=0.7)
            ax.plot(lon1, lat1, 'bo', markersize=4, alpha=0.7)
            
            # Add label at midpoint (optional)
            if show_link_labels:
                mid_lat = (lat0 + lat1) / 2
                mid_lon = (lon0 + lon1) / 2
                ax.annotate(f'CML {cml_id}', xy=(mid_lon, mid_lat), 
                           fontsize=10, alpha=0.7, ha='center', va='center',
                           bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.7, edgecolor='blue'))
    
    # Add PWS stations
    if pws_meta is not None and not pws_meta.empty:
        pws_lats = []
        pws_lons = []
        pws_labels = []
        
        for idx, pws in pws_meta.iterrows():
            if 'Latitude' in pws_meta.columns:
                lat, lon = pws['Latitude'], pws['Longitude']
                station_id = pws.get('Station ID', f'PWS_{idx}')
            else:
                lat, lon = pws['lat'], pws['lon']
                station_id = pws.get('station_id', f'PWS_{idx}')
            
            pws_lats.append(lat)
            pws_lons.append(lon)
            pws_labels.append(station_id)
        
        ax.scatter(pws_lons, pws_lats, c='green', s=50, marker='o', 
                  alpha=0.7, edgecolors='darkgreen', linewidths=1.5, label='PWS Stations', zorder=5)
        
        # Add labels for PWS (show first 10 to avoid clutter)
        for i, (lon, lat, label) in enumerate(zip(pws_lons[:10], pws_lats[:10], pws_labels[:10])):
            ax.annotate(label, xy=(lon, lat), xytext=(5, 5), textcoords='offset points',
                       fontsize=10, alpha=0.8, color='green')
    
    # Add ASOS stations
    if asos_meta is not None and not asos_meta.empty:
        asos_lats = []
        asos_lons = []
        asos_labels = []
        
        for idx, asos in asos_meta.iterrows():
            if 'Latitude' in asos_meta.columns:
                lat, lon = asos['Latitude'], asos['Longitude']
                station_id = asos.get('Station ID', f'ASOS_{idx}')
            else:
                lat, lon = asos['lat'], asos['lon']
                station_id = asos.get('station_id', f'ASOS_{idx}')
            
            asos_lats.append(lat)
            asos_lons.append(lon)
            asos_labels.append(station_id)
        
        ax.scatter(asos_lons, asos_lats, c='red', s=80, marker='s', 
                  alpha=0.8, edgecolors='darkred', linewidths=2, label='ASOS Stations', zorder=6)
        
        # Add labels for ASOS
        for lon, lat, label in zip(asos_lons, asos_lats, asos_labels):
            ax.annotate(label, xy=(lon, lat), xytext=(5, 5), textcoords='offset points',
                       fontsize=12, alpha=0.9, color='red', fontweight='bold')
    
    # Add legend - LARGER
    ax.legend(loc='upper right', fontsize=14, framealpha=0.9)
    
    # Add coordinate info in corner - LARGER (2 decimal places)
    info_text = f'Center: ({center_lat:.2f}°, {center_lon:.2f}°)\n'
    info_text += f'Range: Lat [{lat_range[0]:.2f}°, {lat_range[1]:.2f}°]\n'
    info_text += f'        Lon [{lon_range[0]:.2f}°, {lon_range[1]:.2f}°]'
    
    ax.text(0.02, 0.98, info_text, transform=ax.transAxes, 
           fontsize=12, verticalalignment='top', 
           bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))
    
    plt.tight_layout()
    print("✓ Matplotlib map created")
    
    return fig, ax



# ============================================================================
# CELL 5: Data Summary
# ============================================================================

def summarize_analysis_data(analysis_data):
    """Complete summary of all datasets in analysis_data."""
    
    print("=" * 80)
    print("ANALYSIS DATA SUMMARY")
    print("=" * 80)
    
    # Get analysis period from info
    info = analysis_data.get('info', {})
    period = info.get('analysis_period', (None, None))
    interval = info.get('target_interval', 'original')
    pws_source = info.get('pws_source', 'unknown')
    
    print(f"\nPeriod:   {period[0]} → {period[1]}")
    print(f"Interval: {interval}")
    print(f"PWS:      {pws_source}")
    
    print("\n" + "-" * 80)
    print(f"{'DATASET':<20} {'STATIONS/LINKS':<15} {'PARAMETERS':<15} {'RECORDS':<10}")
    print("-" * 80)
    
    # 1. CML (Sublinks) - FIRST
    if 'cml' in analysis_data and analysis_data['cml']:
        n_params = len(analysis_data['cml'])
        first_param = list(analysis_data['cml'].values())[0]
        n_sublinks = len(first_param.columns) if not first_param.empty else 0
        n_records = len(first_param) if not first_param.empty else 0
        params = ', '.join(sorted(analysis_data['cml'].keys()))
        
        print(f"{'CML (Sublinks)':<20} {f'{n_sublinks} sublinks':<15} {n_params:<15} {n_records:<10}")
        print(f"{'':20} → {params}")
    else:
        print(f"{'CML (Sublinks)':<20} {'NO DATA':<15}")
    
    # 2. ASOS
    if 'asos' in analysis_data and analysis_data['asos']:
        n_params = len(analysis_data['asos'])
        first_param = list(analysis_data['asos'].values())[0]
        n_stations = len(first_param.columns) if not first_param.empty else 0
        n_records = len(first_param) if not first_param.empty else 0
        params = ', '.join(sorted(analysis_data['asos'].keys()))
        
        print(f"{'ASOS':<20} {f'{n_stations} stations':<15} {n_params:<15} {n_records:<10}")
        print(f"{'':20} → {params}")
    else:
        print(f"{'ASOS':<20} {'NO DATA':<15}")
    
    # 3. PWS
    if 'pws' in analysis_data and analysis_data['pws']:
        n_params = len(analysis_data['pws'])
        first_param = list(analysis_data['pws'].values())[0]
        n_stations = len(first_param.columns) if not first_param.empty else 0
        n_records = len(first_param) if not first_param.empty else 0
        params = ', '.join(sorted(analysis_data['pws'].keys()))
        
        print(f"{f'PWS ({pws_source})':<20} {f'{n_stations} stations':<15} {n_params:<15} {n_records:<10}")
        print(f"{'':20} → {params}")
    else:
        print(f"{'PWS':<20} {'NO DATA':<15}")
    
    print("-" * 80)
    
    # All unique parameters across datasets
    all_params = set()
    for source in ['asos', 'pws', 'cml']:
        if source in analysis_data and analysis_data[source]:
            all_params.update(analysis_data[source].keys())
    
    if all_params:
        print(f"\nAll Parameters ({len(all_params)}): {', '.join(sorted(all_params))}")
    
    print("=" * 80)


# ============================================================================
# DIAGNOSTIC FUNCTIONS
# ============================================================================

def diagnose_dataframe_columns(df, name="DataFrame"):
    """
    Diagnose issues with DataFrame columns that might prevent plotting.
    
    Parameters
    ----------
    df : pd.DataFrame
        DataFrame to diagnose
    name : str
        Name for the DataFrame (for display)
    
    Returns
    -------
    dict with diagnostic information
    """
    print(f"\n{'='*80}")
    print(f"DIAGNOSTICS: {name}")
    print(f"{'='*80}")
    
    if df.empty:
        print("  ⚠ DataFrame is EMPTY")
        return {'empty': True}
    
    print(f"  Shape: {df.shape[0]} rows × {df.shape[1]} columns")
    print(f"  Index type: {type(df.index).__name__}")
    print(f"  Index range: {df.index.min()} → {df.index.max()}")
    
    # Check column types
    print(f"\n  Column Analysis:")
    numeric_cols = []
    non_numeric_cols = []
    empty_cols = []
    problematic_cols = []
    
    for col in df.columns:
        col_data = df[col]
        
        # Check data type
        dtype = col_data.dtype
        is_numeric = pd.api.types.is_numeric_dtype(col_data)
        
        # Check for non-numeric values
        if is_numeric:
            # Try to convert to numeric to catch mixed types
            try:
                pd.to_numeric(col_data, errors='raise')
                numeric_cols.append(col)
            except (TypeError, ValueError):
                problematic_cols.append((col, "Mixed numeric/non-numeric"))
                non_numeric_cols.append(col)
        else:
            non_numeric_cols.append(col)
        
        # Check if column is empty
        if col_data.isna().all():
            empty_cols.append(col)
    
    print(f"    ✓ Numeric columns: {len(numeric_cols)}")
    if numeric_cols:
        print(f"      Examples: {numeric_cols[:5]}{'...' if len(numeric_cols) > 5 else ''}")
    
    if non_numeric_cols:
        print(f"    ⚠ Non-numeric columns: {len(non_numeric_cols)}")
        print(f"      Examples: {non_numeric_cols[:5]}{'...' if len(non_numeric_cols) > 5 else ''}")
    
    if empty_cols:
        print(f"    ⚠ Empty (all NaN) columns: {len(empty_cols)}")
        print(f"      Examples: {empty_cols[:5]}{'...' if len(empty_cols) > 5 else ''}")
    
    if problematic_cols:
        print(f"    ⚠ Problematic columns: {len(problematic_cols)}")
        for col, issue in problematic_cols[:5]:
            print(f"      - {col}: {issue}")
    
    # Sample column names
    print(f"\n  Column Names (first 20):")
    for i, col in enumerate(df.columns[:20]):
        dtype = df[col].dtype
        non_null = df[col].notna().sum()
        print(f"    {i+1:2d}. '{col}' (dtype: {dtype}, non-null: {non_null}/{len(df)})")
    
    if len(df.columns) > 20:
        print(f"    ... and {len(df.columns) - 20} more columns")
    
    # Check for data in each column
    print(f"\n  Data Availability:")
    cols_with_data = []
    cols_without_data = []
    
    for col in df.columns:
        non_null_count = df[col].notna().sum()
        if non_null_count > 0:
            cols_with_data.append((col, non_null_count))
        else:
            cols_without_data.append(col)
    
    print(f"    Columns with data: {len(cols_with_data)}")
    if cols_with_data:
        print(f"      Top 5: {[f'{c}({n})' for c, n in cols_with_data[:5]]}")
    
    if cols_without_data:
        print(f"    Columns without data: {len(cols_without_data)}")
        print(f"      Examples: {cols_without_data[:5]}{'...' if len(cols_without_data) > 5 else ''}")
    
    print(f"{'='*80}\n")
    
    return {
        'numeric_cols': numeric_cols,
        'non_numeric_cols': non_numeric_cols,
        'empty_cols': empty_cols,
        'problematic_cols': problematic_cols,
        'cols_with_data': cols_with_data,
        'cols_without_data': cols_without_data
    }


def diagnose_analysis_data(analysis_data, parameter=None):
    """
    Diagnose all datasets in analysis_data to find column issues.
    
    Parameters
    ----------
    analysis_data : dict
        The analysis_data dictionary
    parameter : str, optional
        Specific parameter to diagnose (if None, diagnoses all)
    """
    print("\n" + "="*80)
    print("ANALYSIS DATA DIAGNOSTICS")
    print("="*80)
    
    for source in ['asos', 'pws', 'cml']:
        if source not in analysis_data or not analysis_data[source]:
            print(f"\n{source.upper()}: No data")
            continue
        
        print(f"\n{source.upper()}: {len(analysis_data[source])} parameters")
        
        params_to_check = [parameter] if parameter else list(analysis_data[source].keys())
        
        for param in params_to_check:
            if param not in analysis_data[source]:
                continue
            
            df = analysis_data[source][param]
            diagnose_dataframe_columns(df, f"{source.upper()} - {param}")
    
    print("=" * 80)




def diagnose_dataframe_columns(df, name="DataFrame"):
    """
    Diagnose issues with DataFrame columns that might prevent plotting.
    
    Parameters
    ----------
    df : pd.DataFrame
        DataFrame to diagnose
    name : str
        Name for the DataFrame (for display)
    
    Returns
    -------
    dict with diagnostic information
    """
    print(f"\n{'='*80}")
    print(f"DIAGNOSTICS: {name}")
    print(f"{'='*80}")
    
    if df.empty:
        print("  ⚠ DataFrame is EMPTY")
        return {'empty': True}
    
    print(f"  Shape: {df.shape[0]} rows × {df.shape[1]} columns")
    print(f"  Index type: {type(df.index).__name__}")
    print(f"  Index range: {df.index.min()} → {df.index.max()}")
    
    # Check column types
    print(f"\n  Column Analysis:")
    numeric_cols = []
    non_numeric_cols = []
    empty_cols = []
    problematic_cols = []
    
    for col in df.columns:
        col_data = df[col]
        
        # Check data type
        dtype = col_data.dtype
        is_numeric = pd.api.types.is_numeric_dtype(col_data)
        
        # Check for non-numeric values
        if is_numeric:
            # Try to convert to numeric to catch mixed types
            try:
                pd.to_numeric(col_data, errors='raise')
                numeric_cols.append(col)
            except (TypeError, ValueError):
                problematic_cols.append((col, "Mixed numeric/non-numeric"))
                non_numeric_cols.append(col)
        else:
            non_numeric_cols.append(col)
        
        # Check if column is empty
        if col_data.isna().all():
            empty_cols.append(col)
    
    print(f"    ✓ Numeric columns: {len(numeric_cols)}")
    if numeric_cols:
        print(f"      Examples: {numeric_cols[:5]}{'...' if len(numeric_cols) > 5 else ''}")
    
    if non_numeric_cols:
        print(f"    ⚠ Non-numeric columns: {len(non_numeric_cols)}")
        print(f"      Examples: {non_numeric_cols[:5]}{'...' if len(non_numeric_cols) > 5 else ''}")
    
    if empty_cols:
        print(f"    ⚠ Empty (all NaN) columns: {len(empty_cols)}")
        print(f"      Examples: {empty_cols[:5]}{'...' if len(empty_cols) > 5 else ''}")
    
    if problematic_cols:
        print(f"    ⚠ Problematic columns: {len(problematic_cols)}")
        for col, issue in problematic_cols[:5]:
            print(f"      - {col}: {issue}")
    
    # Sample column names
    print(f"\n  Column Names (first 20):")
    for i, col in enumerate(df.columns[:20]):
        dtype = df[col].dtype
        non_null = df[col].notna().sum()
        print(f"    {i+1:2d}. '{col}' (dtype: {dtype}, non-null: {non_null}/{len(df)})")
    
    if len(df.columns) > 20:
        print(f"    ... and {len(df.columns) - 20} more columns")
    
    # Check for data in each column
    print(f"\n  Data Availability:")
    cols_with_data = []
    cols_without_data = []
    
    for col in df.columns:
        non_null_count = df[col].notna().sum()
        if non_null_count > 0:
            cols_with_data.append((col, non_null_count))
        else:
            cols_without_data.append(col)
    
    print(f"    Columns with data: {len(cols_with_data)}")
    if cols_with_data:
        print(f"      Top 5: {[f'{c}({n})' for c, n in cols_with_data[:5]]}")
    
    if cols_without_data:
        print(f"    Columns without data: {len(cols_without_data)}")
        print(f"      Examples: {cols_without_data[:5]}{'...' if len(cols_without_data) > 5 else ''}")
    
    print(f"{'='*80}\n")
    
    return {
        'numeric_cols': numeric_cols,
        'non_numeric_cols': non_numeric_cols,
        'empty_cols': empty_cols,
        'problematic_cols': problematic_cols,
        'cols_with_data': cols_with_data,
        'cols_without_data': cols_without_data
    }


def diagnose_analysis_data(analysis_data, parameter=None):
    """
    Diagnose all datasets in analysis_data to find column issues.
    
    Parameters
    ----------
    analysis_data : dict
        The analysis_data dictionary
    parameter : str, optional
        Specific parameter to diagnose (if None, diagnoses all)
    """
    print("\n" + "="*80)
    print("ANALYSIS DATA DIAGNOSTICS")
    print("="*80)
    
    for source in ['asos', 'pws', 'cml']:
        if source not in analysis_data or not analysis_data[source]:
            print(f"\n{source.upper()}: No data")
            continue
        
        print(f"\n{source.upper()}: {len(analysis_data[source])} parameters")
        
        params_to_check = [parameter] if parameter else list(analysis_data[source].keys())
        
        for param in params_to_check:
            if param not in analysis_data[source]:
                continue
            
            df = analysis_data[source][param]
            diagnose_dataframe_columns(df, f"{source.upper()} - {param}")
    
    print("=" * 80)



from math import radians, cos, sin, asin, sqrt

def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate distance between two points on Earth (km)"""
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    return 6371 * c  # Earth radius in km







def filter_cml_links(
    df_metadata: pd.DataFrame,
    freq_range: Optional[Tuple[float, float]] = None,
    length_range: Optional[Tuple[float, float]] = None,
    link_ids: Optional[List[str]] = None,
    min_links: int = 1,
) -> pd.DataFrame:
    """Filter CML links from metadata based on criteria."""
    df = df_metadata.copy()
    
    if freq_range is not None:
        min_freq, max_freq = freq_range
        freq_col = next((c for c in ['frequency', 'freq', 'Frequency'] if c in df.columns), None)
        if freq_col:
            df = df[(df[freq_col] >= min_freq) & (df[freq_col] <= max_freq)]
    
    if length_range is not None:
        min_len, max_len = length_range
        len_col = next((c for c in ['length', 'Length', 'distance'] if c in df.columns), None)
        if len_col:
            df = df[(df[len_col] >= min_len) & (df[len_col] <= max_len)]
    
    if link_ids is not None:
        df = df.loc[df.index.isin(link_ids)]
    
    if len(df) < min_links:
        print(f"⚠ Warning: Only {len(df)} links found (minimum {min_links} requested)")
    
    return df





def standardize_precip_type(ptype):
    """
    Standardize raw precip_type codes to 5 categories: dry, rain, snow, ice, mix.
    
    This function maps the various raw ASOS precip_type codes to standardized
    categories for consistent analysis and visualization.
    
    Parameters
    ----------
    ptype : str
        Raw precip_type code (e.g., 'NP', 'R', 'S-', 'FZRA', 'P?', 'M ', '?1', etc.)
    
    Returns
    -------
    str
        Standardized category: 'dry', 'rain', 'snow', 'ice', or 'mix'
    """
    if pd.isna(ptype) or ptype in ['', 'nan', 'None']:
        return 'dry'
    
    ptype_str = str(ptype).strip().upper()
    
    # Dry - No precipitation
    if ptype_str in ['NP', 'NP ']:
        return 'dry'
    
    # Missing/error codes → treat as dry
    if ptype_str in ['M', 'M ', '?0', '?1', '?2', '?3']:
        return 'dry'
    
    # Rain (any intensity)
    if ptype_str.startswith('R') or ptype_str in ['R', 'R+', 'R-', 'R ']:
        return 'rain'
    
    # Snow (any intensity)
    if ptype_str.startswith('S') or ptype_str in ['S', 'S+', 'S-', 'S ']:
        return 'snow'
    
    # Ice (freezing rain, ice pellets)
    if ptype_str in ['FZRA', 'FZ', 'ZR', 'PL', 'PL ']:
        return 'ice'
    
    # Mixed/uncertain precipitation
    if ptype_str.startswith('P') or ptype_str in ['P', 'P?', 'P ']:
        return 'mix'
    
    # Default to dry if unknown
    return 'dry'


def prepare_analysis_data(
        datasets: Dict[str, Any],
        analysis_period: Optional[Tuple[datetime, datetime]] = None,
        pws_source: str = 'openmesh',
        parameters: Union[str, List[str]] = 'all',
        target_interval: Optional[str] = None
) -> Dict[str, Dict[str, pd.DataFrame]]:
    """
    Prepare analysis-ready data.
    COMPATIBILITY NOTE: Uses .map() instead of .applymap() for Pandas 3.0+ support.
    """
    print(f"Preparing Analysis Data (Source: {pws_source})")

    analysis_data = {
        'asos': {},
        'pws': {},
        'cml': {},
        'info': {'pws_source': pws_source, 'target_interval': target_interval}
    }

    # 1. Setup Sources & Time
    pws_raw = {}
    pws_type = None
    if pws_source == 'openmesh':
        if datasets['openmesh']['raw'].get('pws'):
            pws_raw = datasets['openmesh']['raw']['pws']
            pws_type = 'netcdf'
    else:
        if datasets['wu']['raw']:
            pws_raw = datasets['wu']['raw']
            pws_type = 'dataframe'

    # Determine Period
    time_ranges = []

    # ASOS Times
    if datasets['asos']['raw']:
        asos_times = []
        for df in datasets['asos']['raw'].values():
            if 'datetime' in df.columns:
                asos_times.extend([df['datetime'].min(), df['datetime'].max()])
        if asos_times: time_ranges.extend([min(asos_times), max(asos_times)])

    # PWS Times
    if pws_raw:
        if pws_type == 'netcdf':
            first_station = list(pws_raw.values())[0]
            if hasattr(first_station, 'time'):
                t0, t1 = pd.to_datetime(first_station.time.values[[0, -1]])
                time_ranges.extend([t0, t1])
        else:
            pws_times = []
            for df in pws_raw.values():
                if 'datetime' in df.columns:
                    pws_times.extend([df['datetime'].min(), df['datetime'].max()])
            if pws_times: time_ranges.extend(pws_times)

    # CML Times
    if datasets['openmesh']['raw'].get('links') is not None:
        ds_links = datasets['openmesh']['raw']['links']
        if hasattr(ds_links, 'time') and len(ds_links.time) > 0:
            t0, t1 = pd.to_datetime(ds_links.time.values[[0, -1]])
            time_ranges.extend([t0, t1])

    if analysis_period:
        common_start, common_end = analysis_period
    elif time_ranges:
        common_start = min(time_ranges)
        common_end = max(time_ranges)
    else:
        common_start = pd.Timestamp.now() - pd.Timedelta(days=1)
        common_end = pd.Timestamp.now()

    print(f"Period: {common_start.date()} to {common_end.date()}")
    analysis_data['info']['analysis_period'] = (common_start, common_end)

    # Helper Context for Silence (suppress internal prints)
    devnull = open(os.devnull, 'w')

    # ---------------------------------------------------------
    # Extract ASOS
    # ---------------------------------------------------------
    if datasets['asos']['raw']:
        with contextlib.redirect_stdout(devnull):
            asos_raw = datasets['asos']['raw']
            param_map = discover_available_parameters(asos_raw, 'dataframe')

            if parameters != 'all':
                params_to_extract = [parameters] if isinstance(parameters, str) else parameters
                param_map = {k: v for k, v in param_map.items() if v in params_to_extract}

            for original_col, standard_name in param_map.items():
                df_param = extract_parameter_from_dataframes(
                    asos_raw, original_col, standard_name, 'asos', common_start, common_end
                )
                if not df_param.empty:
                    if standard_name == 'precip_type':
                        # FIX FOR PANDAS 3.0+ (applymap is removed)
                        try:
                            df_param = df_param.map(standardize_precip_type)
                        except AttributeError:
                            # Fallback just in case, though .map is standard since 2.1
                            df_param = df_param.applymap(standardize_precip_type)

                    analysis_data['asos'][standard_name] = df_param.copy()

        # Summary Print
        if analysis_data['asos']:
            summary = [f"{k} ({len(v.columns)})" for k, v in analysis_data['asos'].items()]
            print(f"ASOS Params: {', '.join(summary)}")

    # ---------------------------------------------------------
    # Extract PWS
    # ---------------------------------------------------------
    if pws_raw:
        with contextlib.redirect_stdout(devnull):
            param_map = discover_available_parameters(pws_raw, pws_type)

            if parameters != 'all':
                params_to_extract = [parameters] if isinstance(parameters, str) else parameters
                param_map = {k: v for k, v in param_map.items() if v in params_to_extract}

            for original_var, standard_name in param_map.items():
                if pws_type == 'netcdf':
                    df_param = extract_parameter_from_netcdf(
                        pws_raw, original_var, standard_name, common_start, common_end
                    )
                else:
                    df_param = extract_parameter_from_dataframes(
                        pws_raw, original_var, standard_name, 'wu', common_start, common_end
                    )

                if not df_param.empty:
                    analysis_data['pws'][standard_name] = df_param

        # Summary Print
        if analysis_data['pws']:
            summary = [f"{k} ({len(v.columns)})" for k, v in analysis_data['pws'].items()]
            print(f"PWS Params:  {', '.join(summary)}")

    # ---------------------------------------------------------
    # Extract CML
    # ---------------------------------------------------------
    if datasets['openmesh']['raw'].get('links') is not None:
        ds_links = datasets['openmesh']['raw']['links']

        if hasattr(ds_links, 'data_vars'):
            with contextlib.redirect_stdout(devnull):
                cml_vars = list(ds_links.data_vars)
                exclude_vars = {'time', 'cml_id', 'sublink_id', 'frequency', 'length',
                                'site_0_lat', 'site_0_lon', 'site_1_lat', 'site_1_lon'}
                cml_vars = [v for v in cml_vars if v not in exclude_vars]

                for var_name in cml_vars:
                    var_lower = var_name.lower()
                    if 'rsl' in var_lower or 'signal' in var_lower:
                        standard_name = 'rsl'
                    elif 'attenuation' in var_lower or 'att' in var_lower:
                        standard_name = 'attenuation'
                    else:
                        standard_name = var_name.lower()

                    try:
                        ds_sel = ds_links.sel(time=slice(common_start, common_end))
                    except:
                        ds_sel = ds_links

                    if var_name not in ds_sel.data_vars: continue
                    var_array = ds_sel[var_name]
                    if 'time' not in var_array.dims: continue

                    time_coords = pd.to_datetime(var_array.time.values)
                    coordinate_pairs = None
                    link_dfs = {}

                    # Metadata (Preferred)
                    if 'openmesh' in datasets and 'meta' in datasets['openmesh']:
                        links_meta = datasets['openmesh']['meta'].get('links_metadata')
                        if links_meta is not None and not links_meta.empty:
                            if 'cml_id' in links_meta.columns and 'sublink_id' in links_meta.columns:
                                coordinate_pairs = list(zip(links_meta['cml_id'], links_meta['sublink_id']))
                                coordinate_pairs = list(set(coordinate_pairs))

                    # Stack (Fallback)
                    if coordinate_pairs is None:
                        try:
                            if hasattr(var_array, 'stack'):
                                var_stacked = var_array.stack(link=('cml_id', 'sublink_id'))
                                if hasattr(var_stacked, 'link'):
                                    coordinate_pairs = [tuple(x) for x in var_stacked.link.values]
                        except:
                            coordinate_pairs = None

                    # Brute Force (Strict)
                    if coordinate_pairs is None:
                        has_cml = 'cml_id' in var_array.coords
                        has_sub = 'sublink_id' in var_array.coords
                        if has_cml and has_sub:
                            cml_ids = var_array.cml_id.values
                            sublink_ids = var_array.sublink_id.values
                            coordinate_pairs = []
                            for c_id in cml_ids:
                                for s_id in sublink_ids:
                                    coordinate_pairs.append((c_id, s_id))

                    if not coordinate_pairs: continue

                    for cml_id, sublink_id in coordinate_pairs:
                        try:
                            var_data = var_array.sel(cml_id=cml_id, sublink_id=sublink_id)
                            if var_data.size == 0: continue
                            values = var_data.values.flatten()

                            if np.isnan(values).all(): continue

                            current_times = time_coords
                            if 'time' in var_data.dims:
                                current_times = pd.to_datetime(var_data.time.values)

                            if len(values) != len(current_times):
                                min_len = min(len(values), len(current_times))
                                values = values[:min_len]
                                current_times = current_times[:min_len]

                            mask = (current_times >= common_start) & (current_times <= common_end)
                            if not mask.any(): continue

                            final_vals = values[mask]
                            if np.isnan(final_vals).all(): continue

                            df_link = pd.DataFrame(
                                {f"{cml_id}_{sublink_id}": final_vals},
                                index=current_times[mask]
                            )
                            df_link = df_link[df_link.index.notna()]
                            if not df_link.empty:
                                link_dfs[f"{cml_id}_{sublink_id}"] = df_link
                        except:
                            continue

                    if link_dfs:
                        df_all = pd.DataFrame()
                        for _, df_link in link_dfs.items():
                            if df_all.empty:
                                df_all = df_link.copy()
                            else:
                                df_all = df_all.join(df_link, how='outer')
                        df_all = df_all.sort_index()
                        if not df_all.empty:
                            analysis_data['cml'][standard_name] = df_all

        # Summary Print


    devnull.close()

    # ---------------------------------------------------------
    # Resample (Suppressed)
    # ---------------------------------------------------------
    if target_interval:
        # Check for case-insensitive 'H' deprecation here too
        if target_interval.endswith('H') and target_interval[:-1].isdigit():
            print(
                f"Note: Converting interval '{target_interval}' to '{target_interval.lower()}' (pandas 2.2+ requirement)")
            target_interval = target_interval.lower()

        print(f"Resampling to {target_interval}...")
        with open(os.devnull, 'w') as devnull:
            with contextlib.redirect_stdout(devnull):
                for source in ['asos', 'pws', 'cml']:
                    for param_name, df in analysis_data[source].items():
                        if df.empty: continue
                        if not isinstance(df.index, pd.DatetimeIndex):
                            try:
                                df.index = pd.to_datetime(df.index)
                            except:
                                continue

                        numeric_cols = df.select_dtypes(include=[np.number]).columns
                        if len(numeric_cols) == 0: continue

                        df_numeric = df[numeric_cols]
                        agg_func = 'sum' if 'rainfall' in param_name else 'mean'
                        try:
                            df_resampled = df_numeric.resample(target_interval).agg(agg_func)
                            if 'rainfall' in param_name:
                                df_resampled = df_resampled.fillna(0)
                            analysis_data[source][param_name] = df_resampled
                        except:
                            pass
    else:
        print("Skipping resampling.")

    return analysis_data


def display_weather_info():
    """Display weather information header."""
    print("\n" + "=" * 70)
    print("DISPLAY WEATHER")
    print("=" * 70)
    print("### Display Precipitation :")
    print("=" * 70)


def adjust_dates(analysis_data, start_date, end_date):
    """
    Find overlapping date range from all datasets in analysis_data and adjust dates.
    
    Parameters
    ----------
    analysis_data : dict
        Dictionary with 'asos', 'pws', 'cml' containing DataFrames
    start_date : datetime
        Original START_DATE
    end_date : datetime
        Original END_DATE
    
    Returns
    -------
    tuple : (adjusted_start, adjusted_end)
        Adjusted dates that match available data
    """
    date_ranges = []
    info = {}
    
    # Get date range from ASOS data
    if 'asos' in analysis_data:
        for param_name, df in analysis_data['asos'].items():
            if isinstance(df, pd.DataFrame) and len(df) > 0 and isinstance(df.index, pd.DatetimeIndex):
                asos_start = df.index.min()
                asos_end = df.index.max()
                date_ranges.append((asos_start, asos_end))
                if 'asos' not in info:
                    info['asos'] = {'start': asos_start, 'end': asos_end}
                info['asos']['start'] = min(info['asos']['start'], asos_start)
                info['asos']['end'] = max(info['asos']['end'], asos_end)
    
    # Get date range from PWS data
    if 'pws' in analysis_data:
        for param_name, df in analysis_data['pws'].items():
            if isinstance(df, pd.DataFrame) and len(df) > 0 and isinstance(df.index, pd.DatetimeIndex):
                pws_start = df.index.min()
                pws_end = df.index.max()
                date_ranges.append((pws_start, pws_end))
                if 'pws' not in info:
                    info['pws'] = {'start': pws_start, 'end': pws_end}
                info['pws']['start'] = min(info['pws']['start'], pws_start)
                info['pws']['end'] = max(info['pws']['end'], pws_end)
    
    # Get date range from CML data
    if 'cml' in analysis_data:
        for param_name, df in analysis_data['cml'].items():
            if isinstance(df, pd.DataFrame) and len(df) > 0 and isinstance(df.index, pd.DatetimeIndex):
                cml_start = df.index.min()
                cml_end = df.index.max()
                date_ranges.append((cml_start, cml_end))
                if 'cml' not in info:
                    info['cml'] = {'start': cml_start, 'end': cml_end}
                info['cml']['start'] = min(info['cml']['start'], cml_start)
                info['cml']['end'] = max(info['cml']['end'], cml_end)
    
    if not date_ranges:
        print("⚠ No date ranges found in analysis_data - using original dates")
        return start_date, end_date
    
    # Find overlapping range: max of all starts, min of all ends
    overlap_start = max([r[0] for r in date_ranges])
    overlap_end = min([r[1] for r in date_ranges])
    
    # Ensure overlap is valid
    if overlap_start >= overlap_end:
        print("⚠ No valid overlap found - using original dates")
        return start_date, end_date
    
    # Clamp to original requested range if overlap extends beyond it
    adjusted_start = max(overlap_start, start_date)
    adjusted_end = min(overlap_end, end_date)
    
    # Ensure adjusted range is valid
    if adjusted_start >= adjusted_end:
        print("⚠ Adjusted range invalid - using overlap range")
        adjusted_start = overlap_start
        adjusted_end = overlap_end
    
    return adjusted_start, adjusted_end


def standardize_precip_type(ptype):
    """
    Standardize raw precip_type codes to 5 categories: dry, rain, snow, ice, mix.
    
    Parameters
    ----------
    ptype : str
        Raw precip_type code (e.g., 'NP', 'R', 'S-', 'FZRA', 'P?', etc.)
    
    Returns
    -------
    str
        Standardized category: 'dry', 'rain', 'snow', 'ice', or 'mix'
    """
    if pd.isna(ptype) or ptype in ['', 'nan', 'None']:
        return 'dry'
    
    ptype_str = str(ptype).strip().upper()
    
    # Dry - No precipitation
    if ptype_str in ['NP', 'NP ']:
        return 'dry'
    
    # Missing/error codes → treat as dry
    if ptype_str in ['M', 'M ', '?0', '?1', '?2', '?3']:
        return 'dry'
    
    # Rain (any intensity)
    if ptype_str.startswith('R') or ptype_str in ['R', 'R+', 'R-', 'R ']:
        return 'rain'
    
    # Snow (any intensity)
    if ptype_str.startswith('S') or ptype_str in ['S', 'S+', 'S-', 'S ']:
        return 'snow'
    
    # Ice (freezing rain, ice pellets)
    if ptype_str in ['FZRA', 'FZ', 'ZR', 'PL', 'PL ']:
        return 'ice'
    
    # Mixed/uncertain precipitation
    if ptype_str.startswith('P') or ptype_str in ['P', 'P?', 'P ']:
        return 'mix'
    
    # Default to dry if unknown
    return 'dry'
