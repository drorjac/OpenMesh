"""
Weather Underground Personal Weather Station (PWS) API Interface
================================================================

A comprehensive Python module for retrieving, processing, and analyzing meteorological 
data from Weather Underground's Personal Weather Station network via the IBM Weather 
Company API.

Key Features
------------
- Automated historical data retrieval with intelligent date range chunking (>31 days)
- Standardized data schema compatible with ASOS (Automated Surface Observing System)
- Hourly aggregated measurements (average, high, low) from PWS network
- Automatic unit conversion and data normalization
- Built-in data quality indicators and validation
- Integrated visualization and analysis utilities

Data Standards
--------------
All meteorological variables are standardized to SI-compatible units for cross-dataset
compatibility and scientific reproducibility:

    Variable          Unit    Description
    ─────────────────────────────────────────────────────────────
    datetime          UTC     Coordinated Universal Time timestamp
    temperature       °C      Air temperature (hourly average)
    dewpoint          °C      Dew point temperature
    wind_speed        m/s     Wind speed (converted from km/h)
    wind_direction    °       Wind direction (degrees from north)
    wind_gust         m/s     Maximum wind gust speed
    precip_amount     mm      Total precipitation accumulation
    precip_rate       mm/h    Precipitation intensity
    humidity          %       Relative humidity
    pressure          hPa     Atmospheric pressure (mb)

API Information
---------------
Base URL: https://api.weather.com/v2/pws
Provider: IBM Weather Company Data (Weather Underground PWS Network)
Data Type: Hourly aggregated observations from personal weather stations

Author: Dror Jacoby
Version: 2.0
Last Updated: 2026-01-16
"""

import requests
from datetime import datetime, timedelta
import json
from typing import Dict, List, Optional, Tuple
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np
import os
from pathlib import Path

# Import from local config (try relative first, then absolute for notebooks)
try:
    from .config import (
        BASE_URL, UNITS, WU_COLUMN_MAPPING, SIMPLE_TO_WU_MAPPING, COLUMN_ORDER,
        CURRENT_PARAMS, IMPERIAL_PARAMS, METRIC_PARAMS,
        get_api_key, check_api_key_status,
    )
except ImportError:
    # Try absolute import for notebooks
    try:
        from weather_underground.config import (
            BASE_URL, UNITS, WU_COLUMN_MAPPING, SIMPLE_TO_WU_MAPPING, COLUMN_ORDER,
            CURRENT_PARAMS, IMPERIAL_PARAMS, METRIC_PARAMS,
            get_api_key, check_api_key_status,
        )
    except ImportError:
        # Last resort: try direct import (if running from weather_underground directory)
        import sys

        config_path = Path(__file__).parent / 'config.py'
        if config_path.exists():
            import importlib.util
            spec = importlib.util.spec_from_file_location("config", config_path)
            config_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(config_module)
            BASE_URL = config_module.BASE_URL
            UNITS = config_module.UNITS
            WU_COLUMN_MAPPING = config_module.WU_COLUMN_MAPPING
            SIMPLE_TO_WU_MAPPING = config_module.SIMPLE_TO_WU_MAPPING
            COLUMN_ORDER = config_module.COLUMN_ORDER
            CURRENT_PARAMS = config_module.CURRENT_PARAMS
            IMPERIAL_PARAMS = config_module.IMPERIAL_PARAMS
            METRIC_PARAMS = config_module.METRIC_PARAMS
            get_api_key = config_module.get_api_key
            check_api_key_status = config_module.check_api_key_status
        else:
            raise ImportError("Cannot find weather_underground.config module")


# ============================================================================
# DATA CONVERSION AND METADATA FUNCTIONS
# ============================================================================

def find_project_root():
    """Find project root by looking for dataset folder"""

    # Try using shared config first (most reliable and modular)
    try:
        from ..config import PROJECT_ROOT
        return PROJECT_ROOT
    except (ImportError, AttributeError):
        pass
    
    # Fallback: manual detection (same logic as shared config)
    current = Path.cwd()
    # First, look for directory containing both 'src' and 'dataset'
    for parent in [current] + list(current.parents):
        if (parent / 'dataset').exists() and (parent / 'src').exists():
            return parent
    
    # Fallback: look for 'dataset' directory
    for parent in [current] + list(current.parents):
        # Check for new structure: dataset/raw/ and dataset/meta/
        if (parent / 'dataset' / 'raw').exists():
            return parent
        # Also check if dataset folder exists at all
        if (parent / 'dataset').exists():
            return parent
    
    # Last resort: assume current directory is project root
    return current


def read_pws_metadata(custom_path=None):
    """
    Read PWS metadata CSV file

    Args:
        custom_path: Optional path to pws_metadata.csv

    Returns:
        DataFrame with PWS metadata
    """

    
    if custom_path:
        df = pd.read_csv(custom_path)
    else:
        root = find_project_root()
        if root is None:
            raise FileNotFoundError("Could not find dataset folder. Please provide custom_path.")
        base = root / 'dataset'
        # Try meta/ first, then legacy meta/openmesh/, then other paths
        for metadata_path in [
            base / 'meta' / 'pws_metadata.csv',
            base / 'meta' / 'openmesh' / 'pws_metadata.csv',
            base / 'weather_station' / 'pws_metadata.csv',
            base / 'weather_station' / 'samples' / 'pws_metadata.csv',
        ]:
            if metadata_path.exists():
                break
        else:
            raise FileNotFoundError(
                "pws_metadata.csv not found. Check dataset/meta/."
            )
        df = pd.read_csv(metadata_path)

    # Clean up
    if 'Unnamed: 0' in df.columns:
        df = df.drop(columns=['Unnamed: 0'])

    return df


def get_station_list(pws_meta):
    """
    Get list of station IDs

    Args:
        pws_meta: DataFrame with PWS metadata

    Returns:
        List of station IDs
    """
    return pws_meta['Station ID'].tolist()


def convert_wu_columns(df, keep_original=False, convert_wind_units=True):
    """
    Convert Weather Underground DataFrame columns to simple names
    Precipitation columns come first!
    
    Also converts wind speed units from km/h to m/s to match ASOS data format.

    Args:
        df: pandas DataFrame with WU data
        keep_original: If True, keep original columns with '_orig' suffix
        convert_wind_units: If True, convert wind speed from km/h to m/s (default: True)

    Returns:
        DataFrame with renamed columns and standardized units
    """


    # Make a copy
    df_clean = df.copy()

    # Keep original columns if requested
    if keep_original:
        for old_col, new_col in WU_COLUMN_MAPPING.items():
            if old_col in df_clean.columns:
                df_clean[f'{new_col}_orig'] = df_clean[old_col]

    # Rename columns
    df_clean = df_clean.rename(columns=WU_COLUMN_MAPPING)

    # Convert wind speed units from km/h to m/s to match ASOS (standardized units)
    # Conversion: 1 km/h = 1000 m / 3600 s = 1/3.6 m/s ≈ 0.277778 m/s
    if convert_wind_units:
        wind_cols = ['wind_speed', 'wind_speed_high', 'wind_speed_low',
                     'wind_gust', 'wind_gust_high', 'wind_gust_low']
        for col in wind_cols:
            if col in df_clean.columns:
                # Convert from km/h to m/s
                df_clean[col] = df_clean[col] / 3.6

    # Reorder columns (precipitation first!)
    available_cols = [col for col in COLUMN_ORDER if col in df_clean.columns]
    other_cols = [col for col in df_clean.columns if col not in available_cols]

    # Precipitation columns first, then rest in order, then any extras
    df_clean = df_clean[available_cols + other_cols]

    return df_clean


def create_metadata_df(df):
    """
    Create a metadata DataFrame with column descriptions

    Args:
        df: pandas DataFrame with clean column names

    Returns:
        DataFrame with metadata (column name, description, units, data type)
    """

    # Metadata with standardized column names (SHARED names marked)
    # Units: °C, m/s (converted from km/h), mm, mm/hr, degrees, %, mb
    metadata = {
        # Precipitation [mm, mm/hr]
        'precip_rate': ('Precipitation Rate (hourly avg)', 'mm/hr', 'float'),      # SHARED
        'precip_amount': ('Precipitation Amount (hourly total)', 'mm', 'float'),   # SHARED

        # Time
        'time_local': ('Observation Time (Local)', 'datetime', 'datetime'),
        'datetime': ('Observation Time (UTC)', 'UTC', 'datetime'),                 # SHARED
        'timestamp_unix': ('Unix Timestamp', 'seconds since epoch', 'int'),

        # Location
        'station_id': ('Weather Station ID', '-', 'object'),                       # SHARED
        'latitude': ('Latitude', 'degrees', 'float'),
        'longitude': ('Longitude', 'degrees', 'float'),
        'timezone': ('Time Zone', '-', 'object'),

        # Temperature [°C]
        'temperature': ('Temperature (hourly avg)', '°C', 'float'),                # SHARED
        'temperature_high': ('Temperature High', '°C', 'float'),
        'temperature_low': ('Temperature Low', '°C', 'float'),
        'dewpoint': ('Dewpoint (hourly avg)', '°C', 'float'),                      # SHARED
        'dewpoint_high': ('Dewpoint High', '°C', 'float'),
        'dewpoint_low': ('Dewpoint Low', '°C', 'float'),
        'heat_index': ('Heat Index (hourly avg)', '°C', 'float'),
        'heat_index_high': ('Heat Index High', '°C', 'float'),
        'heat_index_low': ('Heat Index Low', '°C', 'float'),
        'wind_chill': ('Wind Chill (hourly avg)', '°C', 'float'),
        'wind_chill_high': ('Wind Chill High', '°C', 'float'),
        'wind_chill_low': ('Wind Chill Low', '°C', 'float'),

        # Humidity [%]
        'humidity': ('Humidity (hourly avg)', '%', 'float'),                       # SHARED
        'humidity_high': ('Humidity High', '%', 'float'),
        'humidity_low': ('Humidity Low', '%', 'float'),

        # Wind [m/s, converted from km/h]
        'wind_speed': ('Wind Speed (hourly avg)', 'm/s', 'float'),                 # SHARED
        'wind_speed_high': ('Wind Speed High', 'm/s', 'float'),
        'wind_speed_low': ('Wind Speed Low', 'm/s', 'float'),
        'wind_gust': ('Wind Gust (hourly max)', 'm/s', 'float'),                   # SHARED
        'wind_gust_high': ('Wind Gust High', 'm/s', 'float'),
        'wind_gust_low': ('Wind Gust Low', 'm/s', 'float'),
        'wind_direction': ('Wind Direction (hourly avg)', 'degrees (0-360)', 'float'),  # SHARED

        # Pressure [mb]
        'pressure': ('Pressure (hourly max)', 'mb', 'float'),                      # SHARED
        'pressure_min': ('Pressure Minimum', 'mb', 'float'),
        'pressure_trend': ('Pressure Trend', 'mb', 'float'),

        # Solar/UV
        'solar_radiation_high': ('Solar Radiation High', 'W/m²', 'float'),
        'uv_index_high': ('UV Index High', 'index', 'float'),

        # Quality
        'qc_status': ('Quality Control Status', 'status code', 'int'),
    }

    # Build metadata DataFrame
    meta_data = []
    for col in df.columns:
        if col in metadata:
            desc, units, dtype = metadata[col]
            meta_data.append({
                'column': col,
                'description': desc,
                'units': units,
                'data_type': dtype,
                'has_data': df[col].notna().any(),
                'non_null_count': df[col].notna().sum(),
                'null_count': df[col].isna().sum(),
            })
        else:
            # Unknown column
            meta_data.append({
                'column': col,
                'description': 'Unknown',
                'units': 'Unknown',
                'data_type': str(df[col].dtype),
                'has_data': df[col].notna().any(),
                'non_null_count': df[col].notna().sum(),
                'null_count': df[col].isna().sum(),
            })

    return pd.DataFrame(meta_data)


def get_current_conditions(api_key: str, station_id: str, units: str = 'e') -> Optional[Dict]:
    """
    Fetch current weather conditions for a station

    Args:
        api_key: Weather Underground API key
        station_id: Station ID (e.g., 'KNYNEWYO1127')
        units: 'e' for English, 'm' for metric

    Returns:
        Dictionary with current conditions or None if error
    """
    url = f"{BASE_URL}/observations/current"
    params = {
        'stationId': station_id,
        'format': 'json',
        'units': units,
        'apiKey': api_key
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if 'observations' in data and len(data['observations']) > 0:
            return data
        else:
            print(f"No observations found for station {station_id}")
            return None

    except requests.exceptions.RequestException as e:
        print(f"Error fetching current conditions for {station_id}: {e}")
        return None


def get_historical_data_chunk(api_key: str, station_id: str, start_date: datetime,
                               end_date: datetime, units: str = 'e',
                               data_type: str = 'hourly') -> Optional[Dict]:
    """
    Fetch historical data for a date range (max 31 days per chunk)

    Args:
        api_key: Weather Underground API key
        station_id: Station ID
        start_date: Start datetime
        end_date: End datetime
        units: 'e' for English, 'm' for metric
        data_type: 'hourly', 'all', or 'daily'

    Returns:
        Dictionary with historical observations or None if error
    """
    url = f"{BASE_URL}/history/{data_type}"

    # Format dates as YYYYMMDD
    start_str = start_date.strftime('%Y%m%d')
    end_str = end_date.strftime('%Y%m%d')

    params = {
        'stationId': station_id,
        'format': 'json',
        'units': units,
        'startDate': start_str,
        'endDate': end_str,
        'apiKey': api_key
    }

    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        if 'observations' in data:
            return data
        else:
            print(f"No historical data found for {station_id} ({start_str} to {end_str})")
            return None

    except requests.exceptions.RequestException as e:
        print(f"Error fetching historical data for {station_id} ({start_str} to {end_str}): {e}")
        return None


def get_historical_data_multi_chunk(api_key: str, station_id: str, start_date: datetime,
                                    end_date: datetime, units: str = 'e',
                                    data_type: str = 'hourly') -> Optional[Dict]:
    """
    Fetch historical data for any date range by automatically chunking into 31-day segments

    Args:
        api_key: Weather Underground API key
        station_id: Station ID
        start_date: Start datetime
        end_date: End datetime
        units: 'e' for English, 'm' for metric
        data_type: 'hourly', 'all', or 'daily'

    Returns:
        Dictionary with combined historical observations or None if error
    """
    days_diff = (end_date - start_date).days
    
    # If <= 31 days, just make one call
    if days_diff <= 31:
        return get_historical_data_chunk(api_key, station_id, start_date, end_date, units, data_type)
    
    # Otherwise, split into chunks
    print(f"  📦 Date range spans {days_diff} days - splitting into chunks of max 31 days...")
    
    all_observations = []
    current_start = start_date
    chunk_num = 1
    
    while current_start < end_date:
        # Calculate end of this chunk (max 31 days from start)
        chunk_end = min(current_start + timedelta(days=31), end_date)
        
        print(f"  → Chunk {chunk_num}: {current_start.date()} to {chunk_end.date()}")
        
        # Fetch this chunk
        chunk_data = get_historical_data_chunk(api_key, station_id, current_start, chunk_end, units, data_type)
        
        if chunk_data and 'observations' in chunk_data:
            chunk_obs = chunk_data['observations']
            all_observations.extend(chunk_obs)
            print(f"    ✓ Got {len(chunk_obs)} observations")
        else:
            print(f"    ✗ No data for this chunk")
        
        # Move to next chunk
        current_start = chunk_end + timedelta(days=1)
        chunk_num += 1
    
    if all_observations:
        # Return combined data in same format as single chunk
        combined_data = {
            'observations': all_observations
        }
        print(f"  ✅ Total observations combined: {len(all_observations)}")
        return combined_data
    else:
        print(f"  ❌ No observations retrieved for entire date range")
        return None


def fetch_all_data(api_key: str, station_ids: List[str], start_date: datetime,
                   end_date: datetime, units: str = 'e',
                   fetch_options: Dict = None,
                   show_progress: bool = True) -> Dict[str, Dict]:
    """
    Fetch all available data for multiple stations
    NOW WITH AUTOMATIC CHUNKING FOR LONG DATE RANGES!

    Args:
        api_key: Weather Underground API key
        station_ids: List of station IDs
        start_date: Start datetime for historical data
        end_date: End datetime for historical data
        units: 'e' for English, 'm' for metric
        fetch_options: Dict specifying what to fetch (current, rapid, hourly, daily)
        show_progress: Whether to show progress bars (default: True)

    Returns:
        Dictionary with all data organized by station
    """
    if fetch_options is None:
        fetch_options = {'current': True, 'rapid': True, 'hourly': True, 'daily': True}

    all_data = {}
    
    # Simple progress tracking
    n_stations = len(station_ids)
    station_iter = station_ids

    # Track fetch statistics
    fetch_stats = {'success': 0, 'failed': 0, 'total_obs': 0}
    
    for idx, station_id in enumerate(station_iter):
        # Simple inline progress
        progress = (idx + 1) / n_stations
        bar_len = 20
        filled = int(bar_len * progress)
        bar = '█' * filled + '░' * (bar_len - filled)
        print(f"\r  [{bar}] {idx+1}/{n_stations} {station_id:<15} obs:{fetch_stats['total_obs']:,}", end='', flush=True)
        
        station_data = {
            'station_id': station_id,
            'current': None,
            'rapid': None,
            'hourly': None,
            'daily': None,
            'fetch_time': datetime.now().isoformat()
        }
        
        station_obs = 0

        # Fetch current conditions
        if fetch_options.get('current', False):
            current = get_current_conditions(api_key, station_id, units)
            if current:
                station_data['current'] = current

        # Fetch rapid history (high resolution - last 24 hours only)
        if fetch_options.get('rapid', False):
            rapid = get_rapid_history(api_key, station_id, units)
            if rapid:
                station_data['rapid'] = rapid
                station_obs += len(rapid.get('observations', []))

        # Fetch historical data with automatic chunking
        if fetch_options.get('historical', False):
            historical = get_historical_data_multi_chunk(api_key, station_id, start_date, end_date, units, 'hourly')
            if historical:
                station_data['rapid'] = historical  # Store in 'rapid' key for backwards compatibility
                station_obs += len(historical.get('observations', []))

        # Fetch hourly history (limited to 7 days by API)
        if fetch_options.get('hourly', False):
            days_diff = (end_date - start_date).days
            if days_diff > 7:
                hourly_start = end_date - timedelta(days=7)
            else:
                hourly_start = start_date
            hourly = get_hourly_history(api_key, station_id, hourly_start, end_date, units)
            if hourly:
                station_data['hourly'] = hourly
                station_obs += len(hourly.get('observations', []))

        # Fetch daily summary
        if fetch_options.get('daily', False):
            days_diff = (end_date - start_date).days
            summary_days = min(days_diff, 7)
            daily = get_daily_summary(api_key, station_id, summary_days, units)
            if daily:
                station_data['daily'] = daily

        all_data[station_id] = station_data
        
        # Update stats
        if station_obs > 0:
            fetch_stats['success'] += 1
            fetch_stats['total_obs'] += station_obs
        else:
            fetch_stats['failed'] += 1

    # Final progress line
    print(f"\r  [{'█' * 20}] {n_stations}/{n_stations} Done! ✓ {fetch_stats['total_obs']:,} obs     ")
    
    return all_data


def get_hourly_history(api_key: str, station_id: str, start_date: datetime,
                       end_date: datetime, units: str = 'e') -> Optional[Dict]:
    """
    Fetch hourly historical observations (max 7 days)

    Args:
        api_key: Weather Underground API key
        station_id: Station ID
        start_date: Start datetime
        end_date: End datetime
        units: 'e' for English, 'm' for metric

    Returns:
        Dictionary with hourly observations or None if error
    """
    url = f"{BASE_URL}/observations/hourly/7day"
    params = {
        'stationId': station_id,
        'format': 'json',
        'units': units,
        'apiKey': api_key
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if 'observations' in data:
            # Filter by date range
            observations = data['observations']
            filtered_obs = []

            for obs in observations:
                obs_time = datetime.strptime(obs['obsTimeLocal'][:19], '%Y-%m-%d %H:%M:%S')
                if start_date <= obs_time <= end_date:
                    filtered_obs.append(obs)

            data['observations'] = filtered_obs
            return data
        else:
            print(f"No observations found for station {station_id}")
            return None

    except requests.exceptions.RequestException as e:
        print(f"Error fetching hourly history for {station_id}: {e}")
        return None


def get_daily_summary(api_key: str, station_id: str, num_days: int = 7,
                      units: str = 'e') -> Optional[Dict]:
    """
    Fetch daily summary (max 7 days)

    Args:
        api_key: Weather Underground API key
        station_id: Station ID
        num_days: Number of days (1-7)
        units: 'e' for English, 'm' for metric

    Returns:
        Dictionary with daily summaries or None if error
    """
    # API endpoint supports 7day, 30day
    endpoint = '7day' if num_days <= 7 else '30day'
    url = f"{BASE_URL}/dailysummary/{endpoint}"

    params = {
        'stationId': station_id,
        'format': 'json',
        'units': units,
        'apiKey': api_key
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if 'summaries' in data:
            # Limit to requested number of days
            data['summaries'] = data['summaries'][:num_days]
            return data
        else:
            print(f"No summary data found for station {station_id}")
            return None

    except requests.exceptions.RequestException as e:
        print(f"Error fetching daily summary for {station_id}: {e}")
        return None


def get_rapid_history(api_key: str, station_id: str, units: str = 'e') -> Optional[Dict]:
    """
    Fetch rapid history - high resolution data for last 24 hours (5-10 minute intervals)

    Args:
        api_key: Weather Underground API key
        station_id: Station ID
        units: 'e' for English, 'm' for metric

    Returns:
        Dictionary with rapid history observations or None if error
    """
    url = f"{BASE_URL}/observations/all/1day"
    params = {
        'stationId': station_id,
        'format': 'json',
        'units': units,
        'apiKey': api_key
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if 'observations' in data:
            return data
        else:
            print(f"No rapid history found for station {station_id}")
            return None

    except requests.exceptions.RequestException as e:
        print(f"Error fetching rapid history for {station_id}: {e}")
        return None


def save_to_json(data: Dict, filename: str, output_dir: str = 'output') -> bool:
    """
    Save data to a JSON file

    Args:
        data: Data to save
        filename: Output filename
        output_dir: Output directory (default: 'output')

    Returns:
        True if successful, False otherwise
    """
    try:
        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, filename)

        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)

        print(f"✓ Data saved to {filepath}")
        return True

    except Exception as e:
        print(f"✗ Error saving to file: {e}")
        return False


def validate_date_range(start_date: datetime, end_date: datetime) -> Tuple[datetime, datetime]:
    """
    Validate and adjust date range

    Args:
        start_date: Start datetime
        end_date: End datetime

    Returns:
        Tuple of validated (start_date, end_date)
    """
    now = datetime.now()

    # Ensure end_date is not in the future
    if end_date > now:
        print(f"⚠ End date adjusted from {end_date} to {now} (cannot be in future)")
        end_date = now

    # Ensure start_date is before end_date
    if start_date >= end_date:
        print(f"⚠ Start date must be before end date")
        start_date = end_date - timedelta(days=7)

    # Info about date range
    days_diff = (end_date - start_date).days
    if days_diff > 31:
        print(f"ℹ️  Note: {days_diff} days requested. Will automatically split into chunks of 31 days.")

    return start_date, end_date


def run_wu_pipeline(
        api_key: str,
        station_ids: List[str],
        start_date: datetime,
        end_date: datetime,
        units: str = 'm',
        fetch_options: Dict = None,
        output_dir: Optional[str] = None,
        save_data: bool = False,
        verbose: bool = True
) -> Dict:
    """..."""
    import pandas as pd

    if fetch_options is None:
        fetch_options = {'historical': True}

    # Step 1: Validate dates
    start, end = validate_date_range(start_date, end_date)
    days_range = (end - start).days

    # Step 2: Fetch data
    if verbose:
        print("=" * 70)
        print("WEATHER UNDERGROUND DATA")
        print("=" * 70)
        print(f"Period: {start.date()} to {end.date()} ({days_range} days)")
        print(f"Stations: {len(station_ids)}")

    fetch_start_time = datetime.now()

    all_data = fetch_all_data(api_key, station_ids, start, end, units, fetch_options, show_progress=verbose)

    fetch_duration = (datetime.now() - fetch_start_time).total_seconds()

    if all_data:
        total_obs = sum(len(d.get('rapid', {}).get('observations', []))
                        if 'rapid' in d and d['rapid']
                        else len(d.get('historical', {}).get('observations', []))
        if 'historical' in d and d['historical']
        else 0
                        for d in all_data.values())
        stations_with_data = sum(1 for d in all_data.values()
                                 if d.get('rapid') or d.get('historical'))
        if verbose:
            print(
                f"Fetched {total_obs:,} obs in {fetch_duration:.1f}s ({stations_with_data}/{len(station_ids)} stations)")
    else:
        if verbose:
            print("No data fetched")
        return None

    # Step 3: Convert to DataFrames
    all_dfs = {}
    all_metadata = {}

    for station_id, station_data in all_data.items():
        for data_type in ['current', 'rapid', 'historical', 'hourly', 'daily']:
            if data_type in station_data and station_data[data_type] is not None:
                data = station_data[data_type]

                if isinstance(data, dict):
                    observations = data.get('observations', [data])
                elif isinstance(data, list):
                    observations = data
                else:
                    continue

                if not observations:
                    continue

                df_raw = pd.json_normalize(observations) if isinstance(observations, list) else pd.DataFrame(
                    [observations])

                if 'obsTimeLocal' in df_raw.columns:
                    df_raw['obsTimeLocal'] = pd.to_datetime(df_raw['obsTimeLocal'])
                if 'obsTimeUtc' in df_raw.columns:
                    df_raw['obsTimeUtc'] = pd.to_datetime(df_raw['obsTimeUtc'])

                df_raw = df_raw.sort_values('obsTimeLocal').reset_index(
                    drop=True) if 'obsTimeLocal' in df_raw.columns else df_raw

                df_clean = convert_wu_columns(df_raw)
                metadata = create_metadata_df(df_clean)

                all_dfs[station_id] = {'raw': df_raw, 'clean': df_clean}
                all_metadata[station_id] = metadata
                break

    # Convert daily cumulative precip_amount → hourly amounts
    all_dfs = adjust_precip_cumulative(all_dfs)

    if verbose:
        print(f"Processed {len(all_dfs)} stations")
        print("=" * 70)

    # Step 4: Save data if requested
    if save_data and output_dir:
        from pathlib import Path
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        for station_id, dfs in all_dfs.items():
            csv_file = output_path / f"{station_id}_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.csv"
            dfs['clean'].to_csv(csv_file, index=False)
            if verbose:
                print(f"  Saved: {csv_file}")

    return {
        'raw_data': all_data,
        'dataframes': all_dfs,
        'metadata': all_metadata,
        'summary': {
            'stations': list(all_dfs.keys()),
            'stations_with_data': len(all_dfs),
            'total_observations': total_obs if all_data else 0,
            'date_range': {'start': start.date(), 'end': end.date()},
            'units': units
        },
        'validated_dates': (start, end)
    }


def save_wu(raw_data=None, processed_data=None, output_dir=None, overwrite=False):
    """
    Simple function to save Weather Underground PWS data. Saves all provided data types.
    
    Parameters
    ----------
    raw_data : dict, optional
        {station_id: DataFrame} - Raw data (original API column names)
    processed_data : dict, optional
        {station_id: DataFrame} - Processed data (clean column names)
    output_dir : str or Path, optional
        Output directory. If None, uses default from config.
    overwrite : bool, default False
        If True, overwrite existing files. If False, raise error if file exists.
    
    Examples
    --------
    >>> save_wu(processed_data=processed_data)  # Save processed only
    >>> save_wu(raw_data=raw_data, processed_data=processed_data)  # Save both
    >>> save_wu(processed_data=processed_data, overwrite=True)  # Overwrite if exists
    """

    
    # Get default output directory if not provided
    if output_dir is None:
        try:
            from ..config import OUTPUT_DIRS
            output_dir = OUTPUT_DIRS['wu']
        except ImportError:
            try:
                # Try to find project root (Path is imported at module level)
                current = Path.cwd()
                for parent in [current] + list(current.parents):
                    # New structure: dataset/raw/fetched/wu
                    if (parent / 'dataset' / 'raw' / 'fetched' / 'wu').exists():
                        output_dir = parent / 'dataset' / 'raw' / 'fetched' / 'wu'
                        break
                    # Fallback: old structure
                    if (parent / 'dataset' / 'fetched' / 'wu').exists():
                        output_dir = parent / 'dataset' / 'fetched' / 'wu'
                        break
                else:
                    output_dir = current / 'dataset' / 'raw' / 'fetched' / 'wu'
            except Exception:
                raise ValueError("Could not determine output directory. Please provide output_dir.")
    
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Determine which data to use for date extraction
    data_for_dates = processed_data or raw_data
    start_date = None
    end_date = None
    
    if data_for_dates and len(data_for_dates) > 0:
        first_df = list(data_for_dates.values())[0]
        # Try different datetime column names
        for date_col in ['time_utc', 'time_local', 'obsTimeUtc', 'obsTimeLocal', 'datetime']:
            if date_col in first_df.columns:
                all_dates = pd.concat([df[date_col] for df in data_for_dates.values() if date_col in df.columns])
                start_date = pd.to_datetime(all_dates).min()
                end_date = pd.to_datetime(all_dates).max()
                break
    
    # Format date range for filename
    date_suffix = ''
    if start_date and end_date:
        date_suffix = f'_{start_date.strftime("%Y-%m-%d")}_{end_date.strftime("%Y-%m-%d")}'
    
    results = {}
    
    # Check for existing files if overwrite=False
    if not overwrite:
        files_to_check = []
        if raw_data is not None:
            files_to_check.append(output_dir / f"WU_raw{date_suffix}.csv")
        if processed_data is not None:
            files_to_check.append(output_dir / f"WU{date_suffix}.csv")
        
        existing_files = [f for f in files_to_check if f.exists()]
        if existing_files:
            file_list = '\n  - '.join([str(f.name) for f in existing_files])
            raise FileExistsError(
                f"File(s) already exist:\n  - {file_list}\n\n"
                f"Set overwrite=True to replace, or delete existing files first."
            )
    
    # Save raw data
    if raw_data is not None:
        # Combine all stations
        combined_list = []
        for station_id, df in raw_data.items():
            df_copy = df.copy()
            combined_list.append(df_copy)
        
        if combined_list:
            combined = pd.concat(combined_list, ignore_index=True)
            # Sort by station and datetime
            sort_cols = []
            if 'stationID' in combined.columns:
                sort_cols.append('stationID')
            elif 'station_id' in combined.columns:
                sort_cols.append('station_id')
            if 'obsTimeLocal' in combined.columns:
                sort_cols.append('obsTimeLocal')
            elif 'obsTimeUtc' in combined.columns:
                sort_cols.append('obsTimeUtc')
            elif 'time_local' in combined.columns:
                sort_cols.append('time_local')
            elif 'time_utc' in combined.columns:
                sort_cols.append('time_utc')
            
            if sort_cols:
                combined = combined.sort_values(sort_cols).reset_index(drop=True)
            
            fname = f"WU_raw{date_suffix}.csv"
            fpath = output_dir / fname
            combined.to_csv(fpath, index=False)
            results['raw'] = {'combined': fpath}
            print(f"\nSaving RAW data to: {output_dir.resolve()}")
            print("-" * 40)
            print(f"  ✓ {fname} ({len(combined):,} rows)")
            print("-" * 40)
            print(f"✓ Save complete: {output_dir.resolve()}\n")
    
    # Save processed data
    if processed_data is not None:
        # Combine all stations
        combined_list = []
        for station_id, df in processed_data.items():
            df_copy = df.copy()
            combined_list.append(df_copy)
        
        if combined_list:
            combined = pd.concat(combined_list, ignore_index=True)
            # Sort by station and datetime
            sort_cols = []
            if 'station_id' in combined.columns:
                sort_cols.append('station_id')
            if 'time_local' in combined.columns:
                sort_cols.append('time_local')
            elif 'time_utc' in combined.columns:
                sort_cols.append('time_utc')
            elif 'datetime' in combined.columns:
                sort_cols.append('datetime')
            
            if sort_cols:
                combined = combined.sort_values(sort_cols).reset_index(drop=True)
            
            fname = f"WU{date_suffix}.csv"
            fpath = output_dir / fname
            combined.to_csv(fpath, index=False)
            results['processed'] = {'combined': fpath}
            print(f"\nSaving PROCESSED data to: {output_dir.resolve()}")
            print("-" * 40)
            print(f"  ✓ {fname} ({len(combined):,} rows)")
            print("-" * 40)
            print(f"✓ Save complete: {output_dir.resolve()}\n")
    
    return results


# FIX THE DATA - Convert daily cumulative to hourly amounts
def adjust_precip_cumulative(station_data):
    """
    Convert WU daily cumulative precip_amount to hourly amounts (mm per hour).
    
    WU PWS often report metric.precipTotal as a running total per day (resets at midnight).
    Summing raw values overcounts. We take diff within each day to get mm per hour, then
    sum those for correct total precipitation.
    """
    fixed_data = {}
    
    for station_id, data_dict in station_data.items():
        df = data_dict['clean'].copy()
        
        if 'precip_amount' not in df.columns:
            fixed_data[station_id] = {**data_dict, 'clean': df}
            continue
        time_col = 'time_local' if 'time_local' in df.columns else 'datetime'
        if time_col not in df.columns:
            fixed_data[station_id] = {**data_dict, 'clean': df}
            continue
        
        df = df.sort_values(time_col).reset_index(drop=True)
        df['date'] = pd.to_datetime(df[time_col]).dt.date
        
        # Hourly amounts = diff of cumulative within each day
        df['precip_amount_fixed'] = df.groupby('date')['precip_amount'].diff()
        first_per_day = df.groupby('date').head(1).index
        df.loc[first_per_day, 'precip_amount_fixed'] = df.loc[first_per_day, 'precip_amount']
        df['precip_amount_fixed'] = df['precip_amount_fixed'].clip(lower=0).fillna(0)
        
        df['precip_amount'] = df['precip_amount_fixed']
        df = df.drop(columns=['precip_amount_fixed', 'date'])
        
        fixed_data[station_id] = {**data_dict, 'clean': df}
    
    return fixed_data




def _get_time_col(df):
    """Get time column name (prefer 'datetime' over 'time_local')."""
    return 'datetime' if 'datetime' in df.columns else 'time_local'


def _get_col(df, new_name, old_fallback):
    """Get column using new standardized name with old fallback."""
    return new_name if new_name in df.columns else old_fallback


def plot_precipitation_analysis_multi(station_data: Dict, units: str = 'm', show: bool = False, 
                                       max_stations: int = 4, verbose: bool = False):
    """
    Plot precipitation for multiple stations in one figure (sample of 3-4 stations).
    
    Args:
        station_data: Dictionary with station_id -> {'clean': df, ...}
        units: 'm' for metric, 'e' for imperial
        show: Whether to display the plot
        max_stations: Maximum number of stations to plot (default 4)
        verbose: If True, print detailed statistics
    """
    if not station_data or len(station_data) == 0:
        print("❌ No station data available")
        return
    
    station_ids = list(station_data.keys())[:max_stations]
    unit = 'mm/h' if units == 'm' else 'in/h'
    
    fig, ax = plt.subplots(figsize=(14, 6))
    colors = plt.cm.tab10(np.linspace(0, 1, len(station_ids)))
    
    for i, station_id in enumerate(station_ids):
        df = station_data[station_id]['clean']
        tcol = _get_time_col(df)
        precip_col = _get_col(df, 'precip_rate', 'precip_amount')
        
        if precip_col in df.columns:
            total = df[precip_col].sum()
            ax.plot(df[tcol], df[precip_col], linewidth=1.5, 
                   label=f'{station_id} ({total:.1f} {unit.split("/")[0]})',
                   color=colors[i], alpha=0.8)
    
    ax.set_ylabel(f'Precipitation Rate [{unit}]', fontweight='bold', fontsize=11)
    ax.set_xlabel('Date', fontweight='bold', fontsize=11)
    ax.set_title(f'💧 Precipitation: Sample Stations ({len(station_ids)} of {len(station_data)})', 
                fontsize=13, fontweight='bold')
    ax.set_facecolor('white')
    ax.grid(True, alpha=0.4, color='#999999', linestyle='--')
    ax.tick_params(axis='x', rotation=45, labelsize=9)
    ax.tick_params(axis='y', labelsize=9)
    ax.legend(loc='best', fontsize=9, framealpha=0.9)
    
    plt.tight_layout()
    if show:
        plt.show()
    
    if not verbose:
        for station_id in station_ids:
            df = station_data[station_id]['clean']
            precip_col = _get_col(df, 'precip_amount', 'precip_total')
            if precip_col in df.columns:
                total = df[precip_col].sum()
                events = len(df[df[precip_col] > 0])
                print(f"💧 {station_id}: {total:.1f} mm total, {events} events")


def plot_cumulative_precipitation_multi(station_data: Dict, units: str = 'm', show: bool = False,
                                        max_stations: int = 4, verbose: bool = False):
    """
    Plot cumulative precipitation for multiple stations in one figure.
    
    Uses precip_amount (mm) for cumulative sum - the total accumulated precipitation.
    """
    if not station_data or len(station_data) == 0:
        print("❌ No station data available")
        return
    
    station_ids = list(station_data.keys())[:max_stations]
    unit = 'mm' if units == 'm' else 'in'
    
    fig, ax = plt.subplots(figsize=(14, 6))
    colors = plt.cm.tab10(np.linspace(0, 1, len(station_ids)))
    
    for i, station_id in enumerate(station_ids):
        df = station_data[station_id]['clean']
        tcol = _get_time_col(df)
        # Use precip_amount for cumsum (total precipitation per hour)
        precip_col = _get_col(df, 'precip_amount', 'precip_rate')
        
        if precip_col in df.columns:
            df_plot = df.copy().sort_values(tcol)
            # Cumulative sum of precip_amount (mm per hour)
            df_plot['cumulative'] = df_plot[precip_col].fillna(0).cumsum()
            total = df_plot['cumulative'].iloc[-1]
            
            ax.plot(df_plot[tcol], df_plot['cumulative'], linewidth=2,
                   label=f'{station_id} ({total:.1f} {unit})',
                   color=colors[i], alpha=0.8)
    
    ax.set_ylabel(f'Cumulative Precipitation [{unit}]', fontweight='bold', fontsize=11)
    ax.set_xlabel('Date', fontweight='bold', fontsize=11)
    ax.set_title(f'💧 Cumulative Precipitation: Sample Stations ({len(station_ids)} of {len(station_data)})',
                fontsize=13, fontweight='bold')
    ax.set_facecolor('white')
    ax.grid(True, alpha=0.4, color='#999999', linestyle='--')
    ax.tick_params(axis='x', rotation=45, labelsize=9)
    ax.tick_params(axis='y', labelsize=9)
    ax.legend(loc='best', fontsize=9, framealpha=0.9)
    
    plt.tight_layout()
    if show:
        plt.show()
    
    if not verbose:
        for station_id in station_ids:
            df = station_data[station_id]['clean']
            precip_col = _get_col(df, 'precip_amount', 'precip_total')
            if precip_col in df.columns:
                total = df[precip_col].sum()
                events = len(df[df[precip_col] > 0])
                print(f"📈 {station_id}: {total:.1f} {unit} total, {events} events")


def plot_weather_dashboard_multi(station_data: Dict, units: str = 'm', show: bool = False, 
                                  max_stations: int = 4, verbose: bool = False):
    """
    Plot weather dashboard for multiple stations (sample of 3-4 stations).
    
    Uses standardized column names with fallbacks for old names.
    """
    if not station_data or len(station_data) == 0:
        if verbose:
            print("❌ No station data available")
        return
    
    station_ids = list(station_data.keys())[:max_stations]
    
    fig, axes = plt.subplots(4, 1, figsize=(14, 10))
    colors = plt.cm.tab10(np.linspace(0, 1, len(station_ids)))
    
    for i, station_id in enumerate(station_ids):
        df = station_data[station_id]['clean']
        tcol = _get_time_col(df)
        
        # Temperature (new: 'temperature', old: 'temp_avg')
        temp_col = _get_col(df, 'temperature', 'temp_avg')
        if temp_col in df.columns:
            axes[0].plot(df[tcol], df[temp_col], linewidth=1, 
                        label=station_id, color=colors[i], alpha=0.7)
        
        # Humidity (new: 'humidity', old: 'humidity_avg')
        humidity_col = _get_col(df, 'humidity', 'humidity_avg')
        if humidity_col in df.columns:
            axes[1].plot(df[tcol], df[humidity_col], linewidth=1,
                        label=station_id, color=colors[i], alpha=0.7)
        
        # Wind (new: 'wind_speed', old: 'wind_speed_avg')
        wind_col = _get_col(df, 'wind_speed', 'wind_speed_avg')
        if wind_col in df.columns:
            axes[2].plot(df[tcol], df[wind_col], linewidth=1,
                        label=station_id, color=colors[i], alpha=0.7)
        
        # Precipitation rate
        precip_col = _get_col(df, 'precip_rate', 'precip_amount')
        if precip_col in df.columns:
            axes[3].bar(df[tcol], df[precip_col], width=0.04, 
                       color=colors[i], alpha=0.5, label=station_id)
    
    # Set labels with standardized units
    axes[0].set_ylabel('Temperature [°C]', fontweight='bold')
    axes[0].set_title(f'Weather Dashboard: Sample Stations ({len(station_ids)} of {len(station_data)})', 
                     fontsize=12, fontweight='bold')
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(loc='best', fontsize=8)
    
    axes[1].set_ylabel('Humidity [%]', fontweight='bold')
    axes[1].grid(True, alpha=0.3)
    axes[1].legend(loc='best', fontsize=8)
    
    axes[2].set_ylabel('Wind Speed [m/s]', fontweight='bold')
    axes[2].grid(True, alpha=0.3)
    axes[2].legend(loc='best', fontsize=8)
    
    axes[3].set_ylabel('Precip Rate [mm/h]', fontweight='bold')
    axes[3].set_xlabel('Date', fontweight='bold')
    axes[3].grid(True, alpha=0.3)
    axes[3].legend(loc='best', fontsize=8)
    
    for ax in axes:
        ax.tick_params(axis='x', rotation=45, labelsize=8)
    
    plt.tight_layout()
    if show:
        plt.show()


def plot_weather_dashboard(df: pd.DataFrame, station_id: str, units: str = 'm', 
                           show: bool = False, verbose: bool = False):
    """
    Multi-variable weather dashboard (single station).
    
    Uses standardized column names with fallbacks for old names.
    """
    if df is None or len(df) == 0:
        if verbose:
            print("❌ No data for dashboard")
        return

    tcol = _get_time_col(df)
    fig, axes = plt.subplots(4, 1, figsize=(16, 12))

    # Temperature
    temp_col = _get_col(df, 'temperature', 'temp_avg')
    if temp_col in df.columns:
        axes[0].plot(df[tcol], df[temp_col], linewidth=1.5, color='red')
        axes[0].set_ylabel('Temperature [°C]', fontweight='bold')
        axes[0].set_title(f'Weather Dashboard: {station_id}', fontsize=14, fontweight='bold')
        axes[0].grid(True, alpha=0.3)

    # Humidity
    humidity_col = _get_col(df, 'humidity', 'humidity_avg')
    if humidity_col in df.columns:
        axes[1].plot(df[tcol], df[humidity_col], linewidth=1.5, color='blue')
        axes[1].set_ylabel('Humidity [%]', fontweight='bold')
        axes[1].grid(True, alpha=0.3)

    # Wind
    wind_col = _get_col(df, 'wind_speed', 'wind_speed_avg')
    if wind_col in df.columns:
        axes[2].plot(df[tcol], df[wind_col], linewidth=1.5, color='green')
        wind_gust_col = _get_col(df, 'wind_gust', 'wind_gust_high')
        if wind_gust_col in df.columns:
            axes[2].plot(df[tcol], df[wind_gust_col], linewidth=1, color='darkgreen', alpha=0.5, label='Gusts')
        axes[2].set_ylabel('Wind Speed [m/s]', fontweight='bold')
        axes[2].legend(loc='upper right')
        axes[2].grid(True, alpha=0.3)

    # Precipitation
    precip_col = _get_col(df, 'precip_rate', 'precip_amount')
    if precip_col in df.columns:
        axes[3].bar(df[tcol], df[precip_col], width=0.04, color='dodgerblue', alpha=0.7)
        axes[3].set_ylabel('Precip Rate [mm/h]', fontweight='bold')
        axes[3].set_xlabel('Date', fontweight='bold')
        axes[3].grid(True, alpha=0.3)

    for ax in axes:
        ax.tick_params(axis='x', rotation=45)

    plt.tight_layout()
    if show:
        plt.show()