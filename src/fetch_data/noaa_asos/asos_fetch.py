"""
ASOS 1-Minute Data Functions
============================

Fetch TRUE per-minute precipitation and weather data from IEM.

Source: https://mesonet.agron.iastate.edu/request/asos/1min.phtml

Key feature:
- 1-min `precip` = TRUE precipitation per minute (not hourly running totals)

Note: Data is delayed 18-36 hours (not real-time) due to NCEI collection method.
"""

import pandas as pd
import numpy as np
import requests
from io import StringIO
from datetime import datetime
from dateutil.relativedelta import relativedelta
from pathlib import Path


# =============================================================================
# STATION CONFIG
# =============================================================================

STATIONS = {
    'JFK': {'name': 'JFK Airport', 'color': '#1f77b4', 'ls': '-'},
    'LGA': {'name': 'LaGuardia Airport', 'color': '#ff7f0e', 'ls': '--'},
    'NYC': {'name': 'Central Park', 'color': '#2ca02c', 'ls': ':'}
}


# =============================================================================
# FETCH 1-MINUTE DATA
# =============================================================================

def fetch_1min_chunk(station_id, start_date, end_date, verbose=True):
    """
    Fetch 1-minute ASOS data for a single time chunk.
    """
    url = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos1min.py"
    
    params = {
        'station': station_id,
        'tz': 'UTC',
        'year1': start_date.year,
        'month1': start_date.month,
        'day1': start_date.day,
        'year2': end_date.year,
        'month2': end_date.month,
        'day2': end_date.day,
        'vars': 'tmpf,dwpf,sknt,drct,gust_sknt,gust_drct,ptype,precip',
        'sample': '1min',
        'what': 'download',
        'delim': 'comma',
    }
    
    try:
        response = requests.get(url, params=params, timeout=300)
        
        if response.status_code == 200 and len(response.text) > 100:
            df = pd.read_csv(StringIO(response.text))
            return df
        else:
            return None
    except Exception as e:
        if verbose:
            print(f"  ✗ Error: {e}")
        return None


def fetch_1min_station(station_id, start_date, end_date, verbose=True):
    """
    Fetch 1-minute data for a station in monthly chunks, then merge.
    """
    if verbose:
        print(f"\n{station_id} ({STATIONS.get(station_id, {}).get('name', '')}):")
    
    chunks = []
    current = start_date.replace(day=1)
    
    while current < end_date:
        # End of this month
        next_month = current + relativedelta(months=1)
        chunk_end = min(next_month - relativedelta(days=1), end_date)
        
        if verbose:
            print(f"  {current.strftime('%Y-%m')}... ", end='', flush=True)
        
        df = fetch_1min_chunk(station_id, current, chunk_end, verbose=False)
        
        if df is not None and len(df) > 0:
            chunks.append(df)
            if verbose:
                print(f"✓ {len(df):,} rows")
        else:
            if verbose:
                print("✗ no data")
        
        current = next_month
    
    if len(chunks) == 0:
        if verbose:
            print(f"  ✗ No data retrieved for {station_id}")
        return None
    
    # Merge all chunks
    df_combined = pd.concat(chunks, ignore_index=True)
    df_combined['valid'] = pd.to_datetime(df_combined['valid(UTC)'])
    df_combined = df_combined.drop_duplicates(subset=['valid']).sort_values('valid')
    df_combined = df_combined.reset_index(drop=True)
    
    if verbose:
        print(f"  ✓ Total: {len(df_combined):,} rows")
    
    return df_combined


def fetch_all_stations_1min(station_ids, start_date, end_date, verbose=True):
    """
    Fetch 1-minute data for all stations.
    """
    if verbose:
        print("=" * 60)
        print("FETCHING 1-MINUTE ASOS DATA")
        print(f"Period: {start_date.date()} to {end_date.date()}")
        print("=" * 60)
    
    raw_data = {}
    for station_id in station_ids:
        df = fetch_1min_station(station_id, start_date, end_date, verbose)
        if df is not None:
            raw_data[station_id] = df
    
    if verbose:
        print(f"\n✓ Fetched {len(raw_data)}/{len(station_ids)} stations")
    
    return raw_data


# =============================================================================
# PRECIP TYPE MAPPING
# =============================================================================

# Raw ptype codes mapping
# Note: NCEI/IEM format is mostly undocumented. Codes inferred from METAR standards.
# Source: https://mesonet.agron.iastate.edu/request/asos/1min.phtml
PTYPE_MAP = {
    # Dry - No precipitation
    'NP': 'dry',
    # Rain (any intensity: light-, moderate, heavy+)
    'R': 'rain', 'R+': 'rain', 'R-': 'rain',
    # Snow (any intensity: light-, moderate, heavy+)
    'S': 'snow', 'S+': 'snow', 'S-': 'snow',
    # Precipitation detected but type uncertain
    'P': 'precip', 'P?': 'precip',
    # Missing or sensor error
    'M': 'missing', 'M ': 'missing',
    '?0': 'missing', '?1': 'missing', '?2': 'missing', '?3': 'missing',
}

# Category descriptions for reference
PRECIP_CATEGORIES = {
    'dry': 'No precipitation (NP)',
    'rain': 'Rain - any intensity (R, R+, R-)',
    'snow': 'Snow - any intensity (S, S+, S-)',
    'precip': 'Precipitation detected, type uncertain (P, P?)',
    'missing': 'Missing data or sensor error (M, ?0-?3)',
}


def map_precip_category(ptype):
    """
    Map raw ptype code to simplified category.
    
    Categories
    ----------
    - dry: No precipitation (NP)
    - rain: Rain of any intensity (R, R+, R-)
    - snow: Snow of any intensity (S, S+, S-)
    - precip: Precipitation detected, type uncertain (P, P?)
    - missing: Missing data or sensor error (M, ?0, ?1, ?2, ?3)
    
    Note: NCEI/IEM 1-minute data format is mostly undocumented.
    These mappings are inferred from standard METAR conventions.
    
    Returns
    -------
    str
        Category: 'dry', 'rain', 'snow', 'precip', or 'missing'
    """
    if pd.isna(ptype) or ptype in ['', 'nan', 'None']:
        return 'missing'
    
    ptype_str = str(ptype).strip()
    
    # Direct lookup
    if ptype_str in PTYPE_MAP:
        return PTYPE_MAP[ptype_str]
    
    # Pattern matching for codes not in map
    ptype_upper = ptype_str.upper()
    
    if ptype_upper == 'NP':
        return 'dry'
    if ptype_upper.startswith('R'):
        return 'rain'
    if ptype_upper.startswith('S'):
        return 'snow'
    if ptype_upper.startswith('P'):
        return 'precip'
    if ptype_upper.startswith('M') or ptype_upper.startswith('?'):
        return 'missing'
    
    return 'missing'


# =============================================================================
# CONVERT TO METRIC
# =============================================================================

def convert_to_metric(df, station_id):
    """
    Convert 1-min data to metric units with standardized column names.
    
    Column names are shared with WU data for consistency across datasets.
    For ASOS: Values are INSTANTANEOUS 1-minute readings.
    
    Conversions:
    - tmpf/dwpf (°F) → temperature/dewpoint (°C)
    - sknt/gust_sknt (knots) → wind_speed/wind_gust (m/s)
    - precip (inches) → precip_amount (mm) + precip_rate (mm/hr)
    - ptype → precip_type (raw code) + precip_category (simplified)
    
    Units: °C, m/s, mm, mm/hr, degrees
    """
    out = pd.DataFrame()
    out['datetime'] = pd.to_datetime(df['valid(UTC)'])
    out['station_id'] = station_id
    
    # Temperature: °F → °C
    if 'tmpf' in df.columns:
        out['temperature'] = (pd.to_numeric(df['tmpf'], errors='coerce') - 32) * 5/9
    
    # Dewpoint: °F → °C
    if 'dwpf' in df.columns:
        out['dewpoint'] = (pd.to_numeric(df['dwpf'], errors='coerce') - 32) * 5/9
    
    # Wind speed: knots → m/s
    if 'sknt' in df.columns:
        out['wind_speed'] = pd.to_numeric(df['sknt'], errors='coerce') * 0.51444
    
    # Wind direction: degrees
    if 'drct' in df.columns:
        out['wind_direction'] = pd.to_numeric(df['drct'], errors='coerce')
    
    # Wind gust: knots → m/s
    if 'gust_sknt' in df.columns:
        out['wind_gust'] = pd.to_numeric(df['gust_sknt'], errors='coerce') * 0.51444
    
    # Wind gust direction: degrees
    if 'gust_drct' in df.columns:
        out['wind_gust_direction'] = pd.to_numeric(df['gust_drct'], errors='coerce')
    
    # Precipitation type (raw code + simplified category)
    if 'ptype' in df.columns:
        out['precip_type'] = df['ptype'].astype(str).replace('nan', None)
        out['precip_category'] = out['precip_type'].apply(map_precip_category)
    
    # Precipitation: inches → mm
    # precip_amount = per-minute total, precip_rate = mm/hr
    if 'precip' in df.columns:
        precip_mm = pd.to_numeric(df['precip'], errors='coerce') * 25.4
        out['precip_amount'] = precip_mm    # [mm] precipitation amount per minute
        out['precip_rate'] = precip_mm * 60  # [mm/hr] rate
    
    return out.sort_values('datetime').reset_index(drop=True)


def process_all_stations(raw_data, verbose=True):
    """Convert all stations to metric."""
    if verbose:
        print("\nConverting to metric...")
    
    processed = {}
    for station_id, df in raw_data.items():
        processed[station_id] = convert_to_metric(df, station_id)
        if verbose:
            n = len(processed[station_id])
            precip_sum = processed[station_id]['precip_amount'].sum()
            print(f"  {station_id}: {n:,} rows, total precip = {precip_sum:.1f} mm")
    
    if verbose:
        print("✓ Conversion complete\n")
    
    return processed


# =============================================================================
# GENERAL RESAMPLE FUNCTION
# =============================================================================

def resample_data(df, interval='5min'):
    """
    Resample data to specified interval.
    
    Parameters
    ----------
    df : pd.DataFrame
        Input data with 'datetime' column
    interval : str
        Resampling interval (e.g., '5min', '10min', '15min', '30min', '1H')
    
    Returns
    -------
    pd.DataFrame
        Resampled data
    
    Aggregation rules:
    - precip_total: SUM
    - temp_avg, dewpoint_avg: MEAN
    - wind_speed_avg, wind_direction_avg: MEAN
    - wind_gust_ms: MAX
    - wind_gust_dir_deg: MEAN
    - precip_type, precip_category: MODE (most frequent)
    """
    df = df.copy()
    df = df.set_index('datetime')
    
    agg_dict = {
        'precip_amount': 'sum',
        'precip_rate': 'mean',  # Average rate over interval
        'temperature': 'mean',
        'dewpoint': 'mean',
        'wind_speed': 'mean',
        'wind_direction': 'mean',
        'wind_gust': 'max',
        'wind_gust_direction': 'mean',
    }
    
    # Only aggregate columns that exist
    agg_dict = {k: v for k, v in agg_dict.items() if k in df.columns}
    
    df_resampled = df.resample(interval).agg(agg_dict)
    
    # Handle categorical columns separately (mode)
    def get_mode(x):
        x = x.dropna()
        if len(x) == 0:
            return None
        mode = x.mode()
        return mode.iloc[0] if len(mode) > 0 else None
    
    if 'precip_type' in df.columns:
        ptype_resampled = df['precip_type'].resample(interval).apply(get_mode)
        df_resampled['precip_type'] = ptype_resampled
    
    if 'precip_category' in df.columns:
        pcat_resampled = df['precip_category'].resample(interval).apply(get_mode)
        df_resampled['precip_category'] = pcat_resampled
    
    df_resampled = df_resampled.reset_index()
    
    return df_resampled


def resample_all_stations(processed_data, interval='5min', verbose=True):
    """
    Resample all stations to specified interval.
    
    Parameters
    ----------
    processed_data : dict
        {station_id: DataFrame}
    interval : str
        Resampling interval (e.g., '5min', '10min', '15min', '30min', '1H')
    verbose : bool
        Print progress
    
    Returns
    -------
    dict
        {station_id: resampled DataFrame}
    """
    if verbose:
        print(f"Resampling to {interval} intervals...")
    
    resampled = {}
    for station_id, df in processed_data.items():
        df_res = resample_data(df, interval)
        df_res['station_id'] = station_id
        resampled[station_id] = df_res
        if verbose:
            print(f"  {station_id}: {len(df_res):,} rows")
    
    if verbose:
        print(f"✓ Resampling to {interval} complete\n")
    
    return resampled


# =============================================================================
# ACCUMULATED PRECIPITATION
# =============================================================================

def compute_accumulated(df, start_date=None, end_date=None):
    """
    Compute cumulative precipitation.
    
    Filters to date range first, then computes cumsum (starts at 0).
    """
    df = df.copy()
    df['datetime'] = pd.to_datetime(df['datetime'])
    
    if start_date:
        df = df[df['datetime'] >= pd.to_datetime(start_date)]
    if end_date:
        df = df[df['datetime'] <= pd.to_datetime(end_date)]
    
    df = df.copy()
    df['precip_amount'] = df['precip_amount'].fillna(0)
    df['accumulated_mm'] = df['precip_amount'].cumsum()
    
    return df.reset_index(drop=True)


def compute_accumulated_all(processed_data, start_date=None, end_date=None):
    """Compute accumulated for all stations."""
    accumulated = {}
    for station_id, df in processed_data.items():
        accumulated[station_id] = compute_accumulated(df, start_date, end_date)
    return accumulated


# =============================================================================
# PRECIP TYPE ANALYSIS
# =============================================================================

def get_precip_type_summary(data_dict, use_category=True, verbose=True):
    """
    Summarize precipitation types across all stations.
    
    Parameters
    ----------
    data_dict : dict
        {station_id: DataFrame}
    use_category : bool
        If True, use simplified categories (dry, rain, snow, precip, missing)
        If False, use raw ptype codes
    verbose : bool
        Print summary table
    
    Returns
    -------
    pd.DataFrame
        Summary table with counts per station and type
    """
    summaries = []
    
    # Determine which column to use
    col = 'precip_category' if use_category else 'precip_type'
    
    for station_id, df in data_dict.items():
        # If precip_category requested but doesn't exist, create it on the fly
        if col == 'precip_category' and col not in df.columns:
            if 'precip_type' in df.columns:
                df = df.copy()
                df['precip_category'] = df['precip_type'].apply(map_precip_category)
            else:
                continue
        
        if col not in df.columns:
            continue
        
        # Count types
        type_counts = df[col].value_counts().to_dict()
        
        for ptype, count in type_counts.items():
            if ptype and ptype != 'None' and ptype != 'nan':
                summaries.append({
                    'station_id': station_id,
                    'type': ptype,
                    'count': count
                })
    
    if len(summaries) == 0:
        if verbose:
            print("No precipitation type data found.")
        return pd.DataFrame()
    
    summary_df = pd.DataFrame(summaries)
    
    if verbose:
        print("\nPrecipitation Type Summary:")
        print("-" * 50)
        pivot = summary_df.pivot_table(
            index='type', 
            columns='station_id', 
            values='count', 
            fill_value=0
        )
        # Reorder rows for better display
        if use_category:
            order = ['dry', 'rain', 'snow', 'precip', 'missing']
            order = [o for o in order if o in pivot.index]
            if order:
                pivot = pivot.reindex(order)
        print(pivot.to_string())
        
        # Print percentages
        print("\nPercentages:")
        print("-" * 50)
        pct = pivot.div(pivot.sum()) * 100
        print(pct.round(1).to_string())
        print()
    
    return summary_df


def filter_by_precip_type(df, precip_types):
    """
    Filter data to specific precipitation types.
    
    Parameters
    ----------
    df : pd.DataFrame
        Data with 'precip_type' column
    precip_types : str or list
        Type(s) to filter for (e.g., 'rain', ['rain', 'snow'])
    
    Returns
    -------
    pd.DataFrame
        Filtered data
    """
    if isinstance(precip_types, str):
        precip_types = [precip_types]
    
    return df[df['precip_type'].isin(precip_types)].copy()


# =============================================================================
# FILE I/O
# =============================================================================

def save_raw_data(raw_data_dict, output_dir, start_date=None, end_date=None,
                  save_individual=True, save_combined=True, verbose=True):
    """
    Save raw ASOS data (original US units) to CSV files.
    
    Raw data contains:
    - Temperature in °F (tmpf)
    - Dewpoint in °F (dwpf)
    - Wind speed in knots (sknt)
    - Wind direction in degrees (drct)
    - Precipitation in inches (precip)
    - Original precipitation type codes (ptype)
    
    Parameters
    ----------
    raw_data_dict : dict
        {station_id: DataFrame} with raw data from API
    output_dir : str or Path
        Output directory path
    start_date, end_date : datetime, optional
        Start and end dates for filename
    save_individual : bool
        Save individual station files
    save_combined : bool
        Save combined all-stations file
    verbose : bool
        Print progress and output paths
    
    Returns
    -------
    dict
        {'individual': [paths], 'combined': path or None}
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    saved_files = {'individual': [], 'combined': None}
    
    # Format date range for filename
    date_suffix = ''
    if start_date and end_date:
        start_str = pd.to_datetime(start_date).strftime('%Y-%m-%d')
        end_str = pd.to_datetime(end_date).strftime('%Y-%m-%d')
        date_suffix = f'_{start_str}_{end_str}'
    
    if verbose:
        print(f"\nSaving RAW data to: {output_dir.resolve()}")
        print("-" * 40)
    
    # Individual station files
    if save_individual:
        for station_id, df in raw_data_dict.items():
            fname = f"{station_id}_raw{date_suffix}.csv"
            fpath = output_dir / fname
            df.to_csv(fpath, index=False)
            saved_files['individual'].append(fpath)
            if verbose:
                print(f"  ✓ {fname} ({len(df):,} rows)")
    
    # Combined file
    if save_combined:
        # Combine all stations
        combined_list = []
        for station_id, df in raw_data_dict.items():
            df_copy = df.copy()
            combined_list.append(df_copy)
        
        if combined_list:
            combined = pd.concat(combined_list, ignore_index=True)
            combined = combined.sort_values(['station', 'valid(UTC)']).reset_index(drop=True)
            fname = f"ASOS_raw{date_suffix}.csv"
            fpath = output_dir / fname
            combined.to_csv(fpath, index=False)
            saved_files['combined'] = fpath
            if verbose:
                print(f"  ✓ {fname} ({len(combined):,} rows)")
    
    if verbose:
        print("-" * 40)
        print(f"✓ Save complete: {output_dir.resolve()}\n")
    
    return saved_files
def save_asos(type='standard', datasets=None, raw_data=None, processed_data=None, resampled_data=None, 
              output_dir=None, resample_interval=None, overwrite=False, fetch_location='dataset'):
    """
    Save ASOS data. Use 'type' parameter to select which dataset from 'datasets' dictionary to save.
    
    Parameters
    ----------
    type : str, default 'standard'
        Type of data to save: 'raw', 'standard' (or 'processed'), or 'resampled'
    datasets : dict, optional
        Dictionary with keys 'raw', 'standard', 'resampled' mapping to data dictionaries.
        Example: {'raw': raw_data, 'standard': processed_data, 'resampled': resampled_data}
    raw_data : dict, optional
        {station_id: DataFrame} - Raw data (US units) [backward compatibility]
    processed_data : dict, optional
        {station_id: DataFrame} - Processed/standardized data (metric units) [backward compatibility]
    resampled_data : dict, optional
        {station_id: DataFrame} - Resampled data [backward compatibility]
    output_dir : str or Path, optional
        Output directory. If None, uses default from config based on fetch_location.
    resample_interval : str, optional
        Resample interval for filename (e.g., '5min'). Required for type='resampled'. 
        Defaults from config if not provided.
    overwrite : bool, default False
        If True, overwrite existing files. If False, raise error if file exists.
    fetch_location : str, default 'dataset'
        Where to save data (only used if output_dir is None):
        - 'dataset': Save to main dataset folder (PROJECT_ROOT/dataset/raw/fetched/asos/)
        - 'current': Save to current working directory
    
    Examples
    --------
    >>> all_asos_datasets = {'raw': raw_data, 'standard': processed_data, 'resampled': resampled_data}
    >>> save_asos(type='standard', datasets=all_asos_datasets)  # Save standardized data
    >>> save_asos(type='raw', datasets=all_asos_datasets)  # Save raw data
    >>> save_asos(processed_data=processed_data)  # Old interface still works
    """
    # Get default output directory if not provided
    if output_dir is None:
        try:
            from ..config import get_output_dir
            output_dir = get_output_dir('asos', fetch_location=fetch_location)
        except ImportError:
            try:
                from config import get_output_dir
                output_dir = get_output_dir('asos', fetch_location=fetch_location)
            except ImportError:
                # Final fallback
                from pathlib import Path
                if fetch_location == 'current':
                    output_dir = Path.cwd() / 'asos'
                else:
                    output_dir = Path.cwd() / 'dataset' / 'raw' / 'fetched' / 'asos'
                output_dir.mkdir(parents=True, exist_ok=True)
    
    # Import config for default resample interval
    try:
        from .config import DEFAULT_RESAMPLE_INTERVAL
    except ImportError:
        try:
            from config import DEFAULT_RESAMPLE_INTERVAL
        except ImportError:
            DEFAULT_RESAMPLE_INTERVAL = '5min'
    
    # Handle new interface (type + datasets) vs old interface (raw_data/processed_data/resampled_data)
    # Support 'processed' as alias for 'standard'
    if type == 'processed':
        type = 'standard'
    
    if datasets is not None:
        # New interface: extract data from datasets dictionary based on type
        if type not in datasets:
            raise ValueError(f"Type '{type}' not found in datasets. Available keys: {list(datasets.keys())}")
        
        data_to_save = datasets[type]
        
        if type == 'raw':
            raw_data = data_to_save
            processed_data = None
            resampled_data = None
        elif type == 'standard':
            processed_data = data_to_save
            raw_data = None
            resampled_data = None
        elif type == 'resampled':
            resampled_data = data_to_save
            raw_data = None
            processed_data = None
        else:
            raise ValueError(f"Invalid type: '{type}'. Must be 'raw', 'standard' (or 'processed'), or 'resampled'")
    else:
        # Old interface: determine type from which parameter is provided
        if processed_data is not None:
            type = 'standard'
        elif raw_data is not None:
            type = 'raw'
        elif resampled_data is not None:
            type = 'resampled'
        else:
            raise ValueError("Must provide either 'datasets' parameter (with 'type') or one of: raw_data, processed_data, resampled_data")
    
    # Determine which data to use for date extraction
    data_for_dates = processed_data or raw_data or resampled_data
    start_date = None
    end_date = None
    
    if data_for_dates and len(data_for_dates) > 0:
        first_df = list(data_for_dates.values())[0]
        if 'datetime' in first_df.columns:
            date_col = 'datetime'
        elif 'valid(UTC)' in first_df.columns:
            date_col = 'valid(UTC)'
        elif 'valid' in first_df.columns:
            date_col = 'valid'
        else:
            date_col = None
        
        if date_col:
            all_dates = pd.concat([df[date_col] for df in data_for_dates.values()])
            start_date = pd.to_datetime(all_dates).min()
            end_date = pd.to_datetime(all_dates).max()
    
    # Determine output directory for raw data (api_response subfolder)
    # Only append 'api_response' if output_dir doesn't already end with it
    if type == 'raw':
        if output_dir.name == 'api_response' or str(output_dir).endswith('/api_response') or str(output_dir).endswith('\\api_response'):
            # Already in api_response folder, use as-is
            raw_output_dir = output_dir
        else:
            # Append api_response subfolder
            raw_output_dir = output_dir / 'api_response'
    else:
        raw_output_dir = None  # Not used for other types
    
    # Check for existing files if overwrite=False
    if not overwrite:
        date_suffix = f'_{start_date.strftime("%Y-%m-%d")}_{end_date.strftime("%Y-%m-%d")}' if start_date and end_date else ''
        
        if type == 'raw':
            file_to_check = raw_output_dir / f"ASOS_raw{date_suffix}.csv"
        elif type == 'standard':
            file_to_check = output_dir / f"ASOS_standard{date_suffix}.csv"
        elif type == 'resampled':
            interval = resample_interval if resample_interval else DEFAULT_RESAMPLE_INTERVAL
            file_to_check = output_dir / f"ASOS_{interval}{date_suffix}.csv"
        
        if file_to_check.exists():
            raise FileExistsError(
                f"File already exists: {file_to_check.name}\n\n"
                f"Set overwrite=True to replace, or delete existing file first."
            )
    
    # Save the selected type
    if type == 'raw':
        # Raw data goes to api_response subfolder (unless already there)
        raw_output_dir.mkdir(parents=True, exist_ok=True)
        result = save_raw_data(raw_data, raw_output_dir, start_date=start_date, end_date=end_date,
                               save_combined=True, save_individual=False, verbose=True)
    elif type == 'standard':
        result = save_data(processed_data, output_dir, prefix='standard',
                          start_date=start_date, end_date=end_date,
                          save_combined=True, save_individual=False, verbose=True)
    elif type == 'resampled':
        interval = resample_interval if resample_interval else DEFAULT_RESAMPLE_INTERVAL
        result = save_data(resampled_data, output_dir, prefix=interval,
                          start_date=start_date, end_date=end_date,
                          save_combined=True, save_individual=False, verbose=True)
    
    return result


def save_all_data(processed_data, output_dir, raw_data=None, resampled_data=None,
                  start_date=None, end_date=None, save_raw=False, save_processed=True,
                  save_resampled=False, save_individual=False, save_combined=True,
                  verbose=True, resample_interval=None):
    """
    Unified function to save raw, processed, and/or resampled data.
    
    Parameters
    ----------
    raw_data : dict, optional
        {station_id: DataFrame} with raw data (US units)
    processed_data : dict, optional
        {station_id: DataFrame} with processed data (metric units)
    resampled_data : dict, optional
        {station_id: DataFrame} with resampled data
    output_dir : str or Path
        Output directory path
    start_date, end_date : datetime, optional
        Start and end dates for filename. If None, extracted from data.
    save_raw : bool, default False
        Save raw data
    save_processed : bool, default True
        Save processed data
    save_resampled : bool, default False
        Save resampled data
    save_individual : bool, default False
        Save individual station files
    save_combined : bool, default True
        Save combined all-stations files
    verbose : bool, default True
        Print progress and output paths
    resample_interval : str, optional
        Resample interval for filename (e.g., '5min'). Defaults from config.
    
    Returns
    -------
    dict
        {'raw': saved_files, 'processed': saved_files, 'resampled': saved_files}
    """
    # Import config for default values
    try:
        from .config import DEFAULT_RESAMPLE_INTERVAL
    except ImportError:
        try:
            from config import DEFAULT_RESAMPLE_INTERVAL
        except ImportError:
            DEFAULT_RESAMPLE_INTERVAL = '5min'
    
    # Extract dates from data if not provided
    if start_date is None or end_date is None:
        # Try to get dates from processed_data first (most likely to exist)
        data_to_check = processed_data or raw_data or resampled_data
        if data_to_check and len(data_to_check) > 0:
            first_df = list(data_to_check.values())[0]
            if 'datetime' in first_df.columns:
                date_col = 'datetime'
            elif 'valid(UTC)' in first_df.columns:
                date_col = 'valid(UTC)'
            elif 'valid' in first_df.columns:
                date_col = 'valid'
            else:
                date_col = None
            
            if date_col:
                all_dates = pd.concat([df[date_col] for df in data_to_check.values()])
                if start_date is None:
                    start_date = pd.to_datetime(all_dates).min()
                if end_date is None:
                    end_date = pd.to_datetime(all_dates).max()
    
    results = {}
    
    # Save raw data (to api_response subfolder)
    if save_raw and raw_data is not None:
        # Only append 'api_response' if output_dir doesn't already end with it
        if output_dir.name == 'api_response' or str(output_dir).endswith('/api_response') or str(output_dir).endswith('\\api_response'):
            raw_output_dir = output_dir
        else:
            raw_output_dir = output_dir / 'api_response'
        raw_output_dir.mkdir(parents=True, exist_ok=True)
        results['raw'] = save_raw_data(
            raw_data, raw_output_dir, start_date, end_date,
            save_individual, save_combined, verbose
        )
    
    # Save processed data
    if save_processed and processed_data is not None:
        results['processed'] = save_data(
            processed_data, output_dir, prefix='standard',
            start_date=start_date, end_date=end_date,
            save_individual=save_individual, save_combined=save_combined, verbose=verbose
        )
    
    # Save resampled data
    if save_resampled and resampled_data is not None:
        interval = resample_interval if resample_interval else DEFAULT_RESAMPLE_INTERVAL
        results['resampled'] = save_data(
            resampled_data, output_dir, prefix=interval,
            start_date=start_date, end_date=end_date,
            save_individual=save_individual, save_combined=save_combined, verbose=verbose
        )
    
    return results


def save_data(data_dict, output_dir, prefix='', start_date=None, end_date=None,
              save_individual=True, save_combined=True, verbose=True):
    """
    Save station data to CSV files.
    
    Parameters
    ----------
    data_dict : dict
        {station_id: DataFrame}
    output_dir : str or Path
        Output directory path
    prefix : str
        Prefix for filenames (e.g., '1min', '5min')
    start_date, end_date : datetime, optional
        Start and end dates for filename (format: YYYY-MM-DD_YYYY-MM-DD)
    save_individual : bool
        Save individual station files
    save_combined : bool
        Save combined all-stations file
    verbose : bool
        Print progress and output paths
    
    Returns
    -------
    dict
        {'individual': [paths], 'combined': path or None}
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    saved_files = {'individual': [], 'combined': None}
    
    # Format date range for filename (YYYY-MM-DD_YYYY-MM-DD)
    date_suffix = ''
    if start_date and end_date:
        start_str = pd.to_datetime(start_date).strftime('%Y-%m-%d')
        end_str = pd.to_datetime(end_date).strftime('%Y-%m-%d')
        date_suffix = f'_{start_str}_{end_str}'
    
    if verbose:
        print(f"\nSaving to: {output_dir.resolve()}")
        print("-" * 40)
    
    # Individual station files
    if save_individual:
        for station_id, df in data_dict.items():
            if prefix:
                fname = f"{station_id}_{prefix}{date_suffix}.csv"
            else:
                fname = f"{station_id}{date_suffix}.csv" if date_suffix else f"{station_id}.csv"
            fpath = output_dir / fname
            df.to_csv(fpath, index=False)
            saved_files['individual'].append(fpath)
            if verbose:
                print(f"  ✓ {fname} ({len(df):,} rows)")
    
    # Combined file
    if save_combined:
        combined = pd.concat(data_dict.values(), ignore_index=True)
        combined = combined.sort_values(['station_id', 'datetime']).reset_index(drop=True)
        if prefix:
            fname = f"ASOS_{prefix}{date_suffix}.csv"
        else:
            fname = f"ASOS{date_suffix}.csv" if date_suffix else "ASOS.csv"
        fpath = output_dir / fname
        combined.to_csv(fpath, index=False)
        saved_files['combined'] = fpath
        if verbose:
            print(f"  ✓ {fname} ({len(combined):,} rows)")
    
    if verbose:
        print("-" * 40)
        print(f"✓ Save complete: {output_dir.resolve()}\n")
    
    return saved_files


def print_summary(data_dict, start_date=None, end_date=None, resample_interval=None, 
                  output_dir=None, accumulated_dict=None):
    """
    Print comprehensive summary of processed ASOS data.
    
    Parameters
    ----------
    data_dict : dict
        {station_id: DataFrame} with processed data
    start_date, end_date : datetime, optional
        Analysis period
    resample_interval : str, optional
        Resampling interval (e.g., '5min', '1H')
    output_dir : Path, optional
        Output directory where data was saved
    accumulated_dict : dict, optional
        {station_id: DataFrame} with accumulated precipitation
    """
    print("=" * 70)
    print("ASOS DATA SUMMARY")
    print("=" * 70)
    
    # Period
    if start_date and end_date:
        print(f"\n📅 Period: {start_date.date()} to {end_date.date()}")
    
    # Stations
    print(f"📊 Stations: {len(data_dict)}")
    for station_id in data_dict.keys():
        station_name = STATIONS.get(station_id, {}).get('name', station_id)
        print(f"   - {station_id} ({station_name})")
    
    # Resolution
    if resample_interval:
        print(f"\n⏱️  Resolution: {resample_interval}")
    else:
        print(f"\n⏱️  Resolution: 1-minute (raw)")
    
    # Variables
    if len(data_dict) > 0:
        sample_df = list(data_dict.values())[0]
        variables = [col for col in sample_df.columns if col not in ['datetime', 'station_id']]
        print(f"\n📈 Variables: {', '.join(variables[:5])}")
        if len(variables) > 5:
            print(f"              {', '.join(variables[5:])}")
    
    # Precipitation totals
    print(f"\n💧 Precipitation Totals:")
    for station_id, df in data_dict.items():
        total = df['precip_amount'].sum()
        rainy_mins = (df['precip_amount'] > 0).sum()
        max_precip = df['precip_amount'].max()
        print(f"   {station_id}: {total:.1f} mm total ({rainy_mins:,} rainy minutes, max: {max_precip:.2f} mm)")
    
    # Accumulated (if provided)
    if accumulated_dict:
        print(f"\n📊 Accumulated Precipitation (final values):")
        for station_id, df in accumulated_dict.items():
            final = df['accumulated_mm'].iloc[-1] if len(df) > 0 else 0
            print(f"   {station_id}: {final:.1f} mm")
    
    # Output location
    if output_dir:
        print(f"\n💾 Output directory: {Path(output_dir).resolve()}")
    
    print("\n" + "=" * 70)
    print("✓ COMPLETE")
    print("=" * 70)


def list_available_files(output_dir, prefix='', verbose=True):
    """
    List available ASOS data files in the output directory.
    
    Parameters
    ----------
    output_dir : str or Path
        Directory containing CSV files
    prefix : str
        Filter by prefix (e.g., '1min', '5min'). If empty, lists all.
    verbose : bool
        Print available files
    
    Returns
    -------
    dict
        Dictionary mapping date range strings to file paths
        Format: {'2024-01-01_2024-01-30': Path, ...}
    """
    output_dir = Path(output_dir)
    
    if not output_dir.exists():
        if verbose:
            print(f"✗ Directory not found: {output_dir}")
        return {}
    
    # Find all ASOS files
    if prefix:
        pattern = f"ASOS_{prefix}_*.csv"
    else:
        pattern = "ASOS_*.csv"
    
    files = list(output_dir.glob(pattern))
    
    # Also check for files without date ranges (legacy)
    if prefix:
        legacy_pattern = f"ASOS_{prefix}.csv"
    else:
        legacy_pattern = "ASOS*.csv"
    
    all_files = list(output_dir.glob(legacy_pattern))
    
    # Parse date ranges from filenames
    file_dict = {}
    import re
    
    for file in all_files:
        # Extract date range from filename: ASOS_standard_2024-01-01_2024-01-30.csv
        match = re.search(r'(\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2})\.csv$', file.name)
        if match:
            date_range = match.group(1)
            file_dict[date_range] = file
        else:
            # Legacy file without date range
            file_dict['legacy'] = file
    
    if verbose:
        if file_dict:
            print(f"\nAvailable files in {output_dir}:")
            for date_range, file_path in sorted(file_dict.items()):
                file_size = file_path.stat().st_size / (1024 * 1024)  # MB
                mtime = datetime.fromtimestamp(file_path.stat().st_mtime).strftime('%Y-%m-%d %H:%M')
                print(f"  {date_range}: {file_path.name} ({file_size:.1f} MB, modified: {mtime})")
        else:
            print(f"✗ No matching files found in {output_dir}")
    
    return file_dict


def load_all_data(output_dir, prefix='', verbose=True):
    """
    Load ALL saved ASOS data files from the output directory.
    
    Parameters
    ----------
    output_dir : str or Path
        Directory containing CSV files
    prefix : str
        Filter by prefix (e.g., '1min', '5min'). If empty, loads all files.
    verbose : bool
        Print progress
    
    Returns
    -------
    dict
        Dictionary mapping date ranges (or filenames) to data dictionaries
        Format: {'2024-01-01_2024-01-30': {station_id: DataFrame}, ...}
    """
    output_dir = Path(output_dir)
    
    if not output_dir.exists():
        if verbose:
            print(f"✗ Directory not found: {output_dir}")
        return {}
    
    # Find all ASOS files
    if prefix:
        pattern = f"ASOS_{prefix}_*.csv"
        legacy_pattern = f"ASOS_{prefix}.csv"
    else:
        pattern = "ASOS_*.csv"
        legacy_pattern = "ASOS*.csv"
    
    files = list(output_dir.glob(pattern))
    legacy_files = list(output_dir.glob(legacy_pattern))
    
    # Combine and deduplicate
    all_files = list(set(files + legacy_files))
    
    if not all_files:
        if verbose:
            print(f"✗ No CSV files found in {output_dir}")
        return {}
    
    if verbose:
        print(f"\nLoading {len(all_files)} file(s) from {output_dir}")
        print("-" * 70)
    
    all_data = {}
    import re
    
    for file in sorted(all_files):
        # Extract date range from filename
        match = re.search(r'(\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2})\.csv$', file.name)
        if match:
            date_range = match.group(1)
        else:
            # Legacy file without date range - use filename as key
            date_range = file.stem  # filename without .csv
        
        if verbose:
            print(f"Loading: {file.name}...", end=' ', flush=True)
        
        try:
            df = pd.read_csv(file)
            df['datetime'] = pd.to_datetime(df['datetime'])
            df.set_index('datetime', inplace=True)
            
            # Split by station_id
            if 'station_id' in df.columns:
                data_dict = {}
                for station_id in df['station_id'].unique():
                    station_df = df[df['station_id'] == station_id].copy()
                    station_df.reset_index(inplace=True)
                    data_dict[station_id] = station_df
                
                all_data[date_range] = data_dict
                
                if verbose:
                    total_rows = sum(len(df) for df in data_dict.values())
                    print(f"✓ {len(data_dict)} stations, {total_rows:,} total rows")
            else:
                if verbose:
                    print("⚠ No 'station_id' column - skipping")
                    
        except Exception as e:
            if verbose:
                print(f"✗ Error: {e}")
    
    if verbose:
        print("-" * 70)
        print(f"✓ Loaded {len(all_data)} file(s)")
        for date_range, data_dict in all_data.items():
            print(f"  {date_range}: {len(data_dict)} stations")
    
    return all_data


def select_longest_dataset(all_loaded_data, target_key=None):
    """
    Select dataset with the most rows (longest period) from loaded data.
    
    Parameters
    ----------
    all_loaded_data : dict
        Dictionary mapping date range keys to data dicts
    target_key : str, optional
        Target date range key for comparison (e.g., '2024-01-01_2024-01-30')
    
    Returns
    -------
    tuple
        (selected_data, selected_key, info_message)
    """
    if not all_loaded_data:
        return {}, None, "⚠ No data available"
    
    def count_rows(data_dict):
        """Count total rows across all stations in a dataset."""
        return sum(len(df) for df in data_dict.values())
    
    # Find dataset with most rows
    best_key = max(all_loaded_data.keys(), key=lambda k: count_rows(all_loaded_data[k]))
    selected_data = all_loaded_data[best_key]
    total_rows = count_rows(selected_data)
    
    if target_key and best_key == target_key:
        info = f"✓ Using exact match: {best_key} ({total_rows:,} rows)"
    else:
        info = f"✓ Using dataset with most rows: {best_key} ({total_rows:,} rows)"
    
    return selected_data, best_key, info


def load_data(output_dir, prefix='', date_range=None, verbose=True):
    """
    Load saved ASOS data from CSV files.
    
    Parameters
    ----------
    output_dir : str or Path
        Directory containing CSV files
    prefix : str
        Prefix for filenames (e.g., '1min', '5min'). If empty, loads most recent.
    date_range : str, optional
        Date range string (e.g., '2024-01-01_2024-01-30'). If None, loads most recent.
    verbose : bool
        Print progress
    
    Returns
    -------
    dict
        {station_id: DataFrame} or None if no files found
    """
    output_dir = Path(output_dir)
    
    if not output_dir.exists():
        if verbose:
            print(f"✗ Directory not found: {output_dir}")
        return None
    
    # Find the file to load
    if date_range:
        # Load specific date range file
        if prefix:
            combined_file = output_dir / f"ASOS_{prefix}_{date_range}.csv"
        else:
            # Try to find file with this date range (any prefix)
            files = list(output_dir.glob(f"ASOS_*_{date_range}.csv"))
            if not files:
                if verbose:
                    print(f"✗ No file found with date range: {date_range}")
                return None
            combined_file = files[0]
    elif prefix:
        # Load file with prefix (most recent with date range, or legacy)
        files = list(output_dir.glob(f"ASOS_{prefix}_*.csv"))
        legacy_file = output_dir / f"ASOS_{prefix}.csv"
        if files:
            # Get most recent file with date range
            combined_file = sorted(files, key=lambda x: x.stat().st_mtime, reverse=True)[0]
        elif legacy_file.exists():
            combined_file = legacy_file
        else:
            if verbose:
                print(f"✗ No file found with prefix: {prefix}")
            return None
    else:
        # Find most recent ASOS file
        all_stations_files = list(output_dir.glob("ASOS*.csv"))
        if not all_stations_files:
            if verbose:
                print(f"✗ No ASOS CSV files found in {output_dir}")
            return None
        combined_file = sorted(all_stations_files, key=lambda x: x.stat().st_mtime, reverse=True)[0]
        if verbose:
            print(f"ℹ Loading most recent file: {combined_file.name}")
    
    if not combined_file.exists():
        if verbose:
            print(f"✗ File not found: {combined_file}")
        return None
    
    if verbose:
        print(f"Loading from: {combined_file.name}")
    
    try:
        df = pd.read_csv(combined_file)
        df['datetime'] = pd.to_datetime(df['datetime'])
        df.set_index('datetime', inplace=True)
        
        # Split by station_id
        if 'station_id' in df.columns:
            data_dict = {}
            for station_id in df['station_id'].unique():
                station_df = df[df['station_id'] == station_id].copy()
                station_df.reset_index(inplace=True)
                data_dict[station_id] = station_df
            
            if verbose:
                print(f"✓ Loaded {len(data_dict)} stations")
                for station_id, station_df in data_dict.items():
                    print(f"  {station_id}: {len(station_df):,} rows ({station_df['datetime'].min()} to {station_df['datetime'].max()})")
            
            return data_dict
        else:
            if verbose:
                print("⚠ No 'station_id' column found - returning single DataFrame")
            df.reset_index(inplace=True)
            return {'single_station': df}
            
    except Exception as e:
        if verbose:
            print(f"✗ Error loading file: {e}")
        return None


# =============================================================================
# PLOTTING
# =============================================================================

def plot_precipitation_subplots(data_dict, start_date=None, end_date=None, 
                                 figsize=(14, 10), title_prefix='',
                                 ylim=None, ylims=None, tick_labelsize=None, title_fontsize=12):
    """
    Plot precipitation (mm) for each station in subplots.
    
    Parameters
    ----------
    data_dict : dict
        {station_id: DataFrame}
    start_date, end_date : datetime, optional
        Filter date range
    figsize : tuple
        Figure size
    title_prefix : str
        Prefix for title
    ylim : tuple, optional
        Y-axis limits (min, max). Default: (0, auto). Deprecated: use ylims instead.
    ylims : list or tuple, optional
        Y-axis limits (min, max). Can be [ymin, ymax] or (ymin, ymax). Default: (0, auto)
    tick_labelsize : int, optional
        Font size for tick labels
    title_fontsize : int
        Font size for titles
    """
    import matplotlib.pyplot as plt
    
    n_stations = len(data_dict)
    fig, axes = plt.subplots(n_stations, 1, figsize=figsize, sharex=True)
    
    if n_stations == 1:
        axes = [axes]
    
    for ax, (station_id, df) in zip(axes, data_dict.items()):
        df = df.copy()
        
        if start_date:
            df = df[df['datetime'] >= pd.to_datetime(start_date)]
        if end_date:
            df = df[df['datetime'] <= pd.to_datetime(end_date)]
        
        cfg = STATIONS.get(station_id, {'color': 'blue', 'name': station_id})
        
        ax.plot(df['datetime'], df['precip_amount'], 
                color=cfg['color'], lw=0.5, alpha=0.7)
        
        ax.set_ylabel('Precip (mm)')
        ax.set_title(f"{station_id} ({cfg.get('name', '')})", fontsize=title_fontsize)
        ax.grid(alpha=0.3)
        
        # Use ylims if provided, otherwise ylim, otherwise default to (0, auto)
        ylim_to_use = ylims if ylims is not None else ylim
        if ylim_to_use:
            if isinstance(ylim_to_use, (list, tuple)) and len(ylim_to_use) >= 2:
                ax.set_ylim(ylim_to_use[0], ylim_to_use[1])
            else:
                ax.set_ylim(bottom=0)
        else:
            ax.set_ylim(bottom=0)
        
        if tick_labelsize:
            ax.tick_params(axis='both', labelsize=tick_labelsize)
    
    axes[-1].set_xlabel('Date')
    
    if start_date and end_date:
        date_str = f"{pd.to_datetime(start_date).date()} to {pd.to_datetime(end_date).date()}"
    else:
        date_str = ""
    
    title = f"{title_prefix} Precipitation" if title_prefix else "Precipitation"
    if date_str:
        title += f"\n{date_str}"
    
    fig.suptitle(title, fontsize=title_fontsize)
    plt.tight_layout()
    
    return fig, axes

def plot_weather_subplots(data_dict, params=None, start_date=None, end_date=None,
                          figsize=(14, 12), title_prefix='',
                          ylims=None, tick_labelsize=None, title_fontsize=12,
                          quantile_filter=0.9999):
    """
    Plot multiple weather parameters for all stations.
    
    Parameters
    ----------
    data_dict : dict
        {station_id: DataFrame}
    params : list, optional
        Parameters to plot. Default: ['precip_amount', 'temperature', 'wind_speed']
    start_date, end_date : datetime, optional
        Filter date range
    figsize : tuple
        Figure size
    title_prefix : str
        Prefix for title
    ylims : dict, optional
        Y-axis limits per parameter. E.g., {'precip_amount': (0, 10), 'temperature': (-10, 30)}
    tick_labelsize : int, optional
        Font size for tick labels
    title_fontsize : int
        Font size for titles
    quantile_filter : float, optional
        Filter values above this quantile. Default: 0.9999 (99.99%).
        Set to None to disable filtering.
    """
    import matplotlib.pyplot as plt
    import pandas as pd
    
    if params is None:
        params = ['precip_amount', 'temperature', 'wind_speed']
    
    # Handle ylims: can be a list [ymin, ymax] (apply to all) or dict {param: (ymin, ymax)}
    if ylims is None:
        ylims_dict = {}
    elif isinstance(ylims, (list, tuple)) and len(ylims) == 2:
        ylims_dict = {param: tuple(ylims) for param in params}
    elif isinstance(ylims, dict):
        ylims_dict = ylims
    else:
        ylims_dict = {}
    
    param_labels = {
        'precip_amount': 'Precipitation (mm)',
        'precip_rate': 'Precipitation Rate (mm/hr)',
        'temperature': 'Temperature (°C)',
        'dewpoint': 'Dewpoint (°C)',
        'wind_speed': 'Wind Speed (m/s)',
        'wind_gust': 'Wind Gust (m/s)',
        'wind_direction': 'Wind Direction (°)',
        'visibility_km': 'Visibility (km)',
        'accumulated_mm': 'Accumulated Precip (mm)',
    }
    
    n_params = len(params)
    fig, axes = plt.subplots(n_params, 1, figsize=figsize, sharex=True)
    
    if n_params == 1:
        axes = [axes]
    
    for ax, param in zip(axes, params):
        for station_id, df in data_dict.items():
            df = df.copy()
            
            if start_date:
                df = df[df['datetime'] >= pd.to_datetime(start_date)]
            if end_date:
                df = df[df['datetime'] <= pd.to_datetime(end_date)]
            
            if param not in df.columns:
                continue
            
            # Apply quantile filter
            if quantile_filter is not None:
                upper_limit = df[param].quantile(quantile_filter)
                df.loc[df[param] > upper_limit, param] = np.nan
            
            cfg = STATIONS.get(station_id, {'color': 'blue', 'ls': '-', 'name': station_id})
            
            ax.plot(df['datetime'], df[param], 
                    label=f"{station_id}",
                    color=cfg['color'], ls=cfg.get('ls', '-'), 
                    lw=0.8, alpha=0.7)
        
        ax.set_ylabel(param_labels.get(param, param))
        ax.legend(loc='upper right', fontsize=8)
        ax.grid(alpha=0.3)
        
        if param in ylims_dict:
            ax.set_ylim(ylims_dict[param])
        
        if tick_labelsize:
            ax.tick_params(axis='both', labelsize=tick_labelsize)
    
    axes[-1].set_xlabel('Date')
    
    if start_date and end_date:
        date_str = f"{pd.to_datetime(start_date).date()} to {pd.to_datetime(end_date).date()}"
    else:
        date_str = ""
    
    title = f"{title_prefix} Weather Data" if title_prefix else "Weather Data"
    if date_str:
        title += f"\n{date_str}"
    
    fig.suptitle(title, fontsize=title_fontsize)
    plt.tight_layout()
    
    return fig, axes

def plot_accumulated(accumulated_dict, start_date=None, end_date=None,
                     figsize=(14, 6), ylim=None, ylims=None, tick_labelsize=None, title_fontsize=12):
    """
    Plot accumulated precipitation for all stations.
    
    Parameters
    ----------
    accumulated_dict : dict
        {station_id: DataFrame} with 'accumulated_mm' column
    start_date, end_date : datetime, optional
        For title only
    figsize : tuple
        Figure size
    ylim : tuple, optional
        Y-axis limits (min, max). Default: (0, auto). Deprecated: use ylims instead.
    ylims : list or tuple, optional
        Y-axis limits (min, max). Can be [ymin, ymax] or (ymin, ymax). Default: (0, auto)
    tick_labelsize : int, optional
        Font size for tick labels
    title_fontsize : int
        Font size for titles
    """
    import matplotlib.pyplot as plt
    
    fig, ax = plt.subplots(figsize=figsize)
    
    for station_id, df in accumulated_dict.items():
        cfg = STATIONS.get(station_id, {'color': 'blue', 'ls': '-', 'name': station_id})
        
        ax.plot(df['datetime'], df['accumulated_mm'], 
                label=f"{station_id} ({cfg.get('name', '')})",
                color=cfg['color'], ls=cfg.get('ls', '-'), lw=2)
        
        final = df['accumulated_mm'].iloc[-1]
        ax.annotate(f'{final:.0f} mm', 
                    xy=(df['datetime'].iloc[-1], final),
                    xytext=(5, 0), textcoords='offset points',
                    fontsize=10, fontweight='bold', color=cfg['color'])
    
    ax.set_xlabel('Date')
    ax.set_ylabel('Accumulated Precipitation (mm)')
    
    if start_date and end_date:
        date_str = f"{pd.to_datetime(start_date).date()} to {pd.to_datetime(end_date).date()}"
        ax.set_title(f'Cumulative Precipitation\n{date_str}', fontsize=title_fontsize)
    else:
        ax.set_title('Cumulative Precipitation', fontsize=title_fontsize)
    
    ax.legend(loc='upper left')
    ax.grid(alpha=0.3)
    
    # Use ylims if provided, otherwise ylim, otherwise default to (0, auto)
    ylim_to_use = ylims if ylims is not None else ylim
    if ylim_to_use:
        if isinstance(ylim_to_use, (list, tuple)) and len(ylim_to_use) >= 2:
            ax.set_ylim(ylim_to_use[0], ylim_to_use[1])
        else:
            ax.set_ylim(bottom=0)
    else:
        ax.set_ylim(bottom=0)
    
    if tick_labelsize:
        ax.tick_params(axis='both', labelsize=tick_labelsize)
    
    plt.tight_layout()
    
    return fig, ax


def plot_precip_by_type(data_dict, start_date=None, end_date=None, figsize=(14, 10),
                        ylim=None, ylims=None, tick_labelsize=None, title_fontsize=12,
                        use_category=True):
    """
    Plot precipitation with background colored by precip type.
    
    Parameters
    ----------
    data_dict : dict
        {station_id: DataFrame}
    start_date, end_date : datetime, optional
        Filter date range
    figsize : tuple
        Figure size
    ylim : tuple, optional
        Y-axis limits (min, max). Default: (0, auto). Deprecated: use ylims instead.
    ylims : list or tuple, optional
        Y-axis limits (min, max). Can be [ymin, ymax] or (ymin, ymax). Default: (0, auto)
    tick_labelsize : int, optional
        Font size for tick labels
    title_fontsize : int
        Font size for titles
    use_category : bool
        If True, use simplified categories. If False, use raw ptype codes.
    """
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    
    # Color map for precip categories
    category_colors = {
        'dry': '#f0f0f0',       # very light gray (almost invisible)
        'rain': '#1f77b4',      # blue
        'snow': '#00FFFF',      # cyan
        'precip': '#ff7f0e',    # orange
        'missing': '#d62728',   # red
    }
    
    # Color map for raw ptype codes (fallback)
    ptype_colors = {
        'NP': '#f0f0f0',
        'R': '#1f77b4', 'R+': '#0d4a6b', 'R-': '#5aa3d0',
        'S': '#00FFFF', 'S+': '#00CCCC', 'S-': '#66FFFF',
        'P': '#ff7f0e', 'P?': '#ffb366',
        'M': '#d62728',
    }
    
    n_stations = len(data_dict)
    fig, axes = plt.subplots(n_stations, 1, figsize=figsize, sharex=True)
    
    if n_stations == 1:
        axes = [axes]
    
    col = 'precip_category' if use_category else 'precip_type'
    colors = category_colors if use_category else ptype_colors
    
    for ax, (station_id, df) in zip(axes, data_dict.items()):
        df = df.copy()
        
        if start_date:
            df = df[df['datetime'] >= pd.to_datetime(start_date)]
        if end_date:
            df = df[df['datetime'] <= pd.to_datetime(end_date)]
        
        # If precip_category doesn't exist, create it
        if col == 'precip_category' and col not in df.columns:
            if 'precip_type' in df.columns:
                df['precip_category'] = df['precip_type'].apply(map_precip_category)
            else:
                ax.plot(df['datetime'], df['precip_amount'], lw=0.5, alpha=0.7, color='black')
                continue
        
        if col not in df.columns:
            ax.plot(df['datetime'], df['precip_amount'], lw=0.5, alpha=0.7, color='black')
        else:
            # Get y max for axvspan
            # Use ylims if provided, otherwise ylim, otherwise auto
            ylim_to_use = ylims if ylims is not None else ylim
            if ylim_to_use:
                ymax = ylim_to_use[1] if len(ylim_to_use) >= 2 else df['precip_amount'].max() * 1.1
            else:
                ymax = df['precip_amount'].max() * 1.1 if df['precip_amount'].max() > 0 else 1
            
            # Paint intervals by type (axvspan for each contiguous block)
            df = df.sort_values('datetime').reset_index(drop=True)
            
            # Find contiguous intervals of each type
            df['type_change'] = (df[col] != df[col].shift()).cumsum()
            
            legend_handles = {}
            for _, group in df.groupby('type_change'):
                ptype = group[col].iloc[0]
                if ptype and ptype != 'None' and ptype != 'nan' and ptype != 'dry':
                    color = colors.get(ptype, '#333333')
                    t_start = group['datetime'].iloc[0]
                    t_end = group['datetime'].iloc[-1]
                    ax.axvspan(t_start, t_end, alpha=0.4, color=color, linewidth=0)
                    
                    if ptype not in legend_handles:
                        legend_handles[ptype] = Patch(facecolor=color, alpha=0.4, label=ptype)
            
            # Plot precip line on top
            ax.plot(df['datetime'], df['precip_amount'], lw=0.5, alpha=0.9, color='black')
            
            # Add legend
            if legend_handles:
                # Order legend: rain, snow, precip, missing
                order = ['rain', 'snow', 'precip', 'missing']
                handles = [legend_handles[k] for k in order if k in legend_handles]
                ax.legend(handles=handles, loc='upper right', fontsize=7)
        
        cfg = STATIONS.get(station_id, {'name': station_id})
        ax.set_ylabel('Precip (mm)')
        ax.set_title(f"{station_id} ({cfg.get('name', '')})", fontsize=title_fontsize)
        ax.grid(alpha=0.3)
        
        # Use ylims if provided, otherwise ylim, otherwise default to (0, auto)
        ylim_to_use = ylims if ylims is not None else ylim
        if ylim_to_use:
            if isinstance(ylim_to_use, (list, tuple)) and len(ylim_to_use) >= 2:
                ax.set_ylim(ylim_to_use[0], ylim_to_use[1])
            else:
                ax.set_ylim(bottom=0)
        else:
            ax.set_ylim(bottom=0)
        
        if tick_labelsize:
            ax.tick_params(axis='both', labelsize=tick_labelsize)
    
    axes[-1].set_xlabel('Date')
    
    if start_date and end_date:
        date_str = f"{pd.to_datetime(start_date).date()} to {pd.to_datetime(end_date).date()}"
    else:
        date_str = ""
    
    title = "Precipitation by Type"
    if date_str:
        title += f"\n{date_str}"
    
    fig.suptitle(title, fontsize=title_fontsize)
    plt.tight_layout()
    
    return fig, axes


# =============================================================================
# Pipeline Wrapper Functions (for main.py)
# =============================================================================

def run_asos_pipeline(stations, start_date, end_date, output_dir=None, verbose=True):
    """
    Complete ASOS pipeline: fetch, process, and save.
    
    Wrapper function for use in main.py or scripts.
    
    Parameters
    ----------
    stations : list of str
        Station IDs (e.g., ['JFK', 'LGA', 'NYC'])
    start_date : str or datetime
        Start date (YYYY-MM-DD format if string)
    end_date : str or datetime
        End date (YYYY-MM-DD format if string)
    output_dir : Path, optional
        Output directory (default from config)
    verbose : bool, default True
        Print progress messages
    
    Returns
    -------
    dict or None
        Dictionary with 'processed_data' and 'summary', or None if failed
    """
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
        return None
    
    # Process to metric
    if verbose:
        print("Converting to metric units...")
    processed_data = process_all_stations(raw_data, verbose=verbose)
    
    # Save
    if verbose:
        print("Saving processed data...")
    save_asos(processed_data=processed_data, output_dir=output_dir, overwrite=True)
    
    # Summary
    total_rows = sum(len(df) for df in processed_data.values())
    summary = {
        'stations': list(processed_data.keys()),
        'num_stations': len(processed_data),
        'total_rows': total_rows,
        'start_date': start_date,
        'end_date': end_date
    }
    
    if verbose:
        print(f"✓ Complete: {len(processed_data)} stations, {total_rows:,} total rows")
    
    return {'processed_data': processed_data, 'summary': summary}