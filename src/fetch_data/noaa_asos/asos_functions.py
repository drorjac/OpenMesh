"""
NOAA ASOS Data Processing Functions
====================================

Core functions for fetching and processing ASOS weather data from IEM API.

Author: OpenMesh Project
Date: 2025-11-16
"""

import pandas as pd
import numpy as np
import requests
from io import StringIO
from datetime import datetime
from pathlib import Path


# ============================================================================
# STATION CONFIGURATION
# ============================================================================

STATIONS = {
    'KJFK': {
        'name': 'JFK Airport',
        'location': 'Queens, NY',
        'color': '#1f77b4',
        'linestyle': '-'
    },
    'KLGA': {
        'name': 'LaGuardia Airport',
        'location': 'Queens, NY',
        'color': '#ff7f0e',
        'linestyle': '--'
    },
    'KNYC': {
        'name': 'Central Park',
        'location': 'Manhattan, NY',
        'color': '#2ca02c',
        'linestyle': ':'
    }
}


# ============================================================================
# DATA FETCHING
# ============================================================================

def fetch_station_from_iem(station_id, start_date, end_date, resolution='5min', verbose=True):
    """
    Fetch ASOS data from Iowa Environmental Mesonet (IEM) API
    
    Returns DataFrame with 33 columns including:
    - tmpf, dwpf, relh (temperature, dewpoint, humidity)
    - drct, sknt, gust (wind)
    - p01i (precipitation)
    - alti, mslp (pressure)
    - vsby (visibility)
    """
    BASE_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
    
    params = {
        'station': station_id,
        'data': 'all',
        'year1': start_date.year,
        'month1': start_date.month,
        'day1': start_date.day,
        'year2': end_date.year,
        'month2': end_date.month,
        'day2': end_date.day,
        'tz': 'Etc/UTC',
        'format': 'comma',
        'latlon': 'yes',
        'elev': 'yes',
        'missing': 'M',
        'trace': 'T',
    }
    
    if verbose:
        res_str = '5-min' if resolution == '5min' else 'hourly'
        print(f"Fetching {station_id} ({res_str})... ", end='', flush=True)
    
    try:
        response = requests.get(BASE_URL, params=params, timeout=120)
        
        if response.status_code == 200 and len(response.text) > 100:
            df = pd.read_csv(StringIO(response.text), comment='#')
            if verbose:
                print(f"✓ {len(df):,} records, {len(df.columns)} columns")
            return df
        else:
            if verbose:
                print(f"✗ No data")
            return None
            
    except Exception as e:
        if verbose:
            print(f"✗ Error: {e}")
        return None


def fetch_all_stations(station_ids, start_date, end_date, resolution='5min', verbose=True):
    """Fetch data for multiple stations"""
    if verbose:
        print(f"\n{'='*60}")
        print(f"FETCHING DATA ({resolution})")
        print(f"{'='*60}\n")
    
    raw_data = {}
    for station_id in station_ids:
        df = fetch_station_from_iem(station_id, start_date, end_date, resolution, verbose)
        if df is not None and len(df) > 0:
            raw_data[station_id] = df
    
    if verbose:
        print(f"\n✓ Fetched {len(raw_data)}/{len(station_ids)} stations\n")
    
    return raw_data


# ============================================================================
# DATA CONVERSION
# ============================================================================

def convert_to_standard_format(df, station_id):
    """Convert IEM format to metric units"""
    df = df.copy()
    standard = pd.DataFrame()
    
    standard['datetime'] = pd.to_datetime(df['valid'])
    standard['station_id'] = station_id
    
    # Temperature: F to C
    if 'tmpf' in df.columns:
        standard['temp_c'] = pd.to_numeric(df['tmpf'], errors='coerce')
        standard['temp_c'] = (standard['temp_c'] - 32) * 5/9
    
    # Dewpoint: F to C
    if 'dwpf' in df.columns:
        standard['dewpoint_c'] = pd.to_numeric(df['dwpf'], errors='coerce')
        standard['dewpoint_c'] = (standard['dewpoint_c'] - 32) * 5/9
    
    # Wind: knots to m/s
    if 'sknt' in df.columns:
        standard['wind_speed_ms'] = pd.to_numeric(df['sknt'], errors='coerce') * 0.51444
    
    if 'drct' in df.columns:
        standard['wind_dir_deg'] = pd.to_numeric(df['drct'], errors='coerce')
    
    # Pressure: inHg to hPa
    if 'alti' in df.columns:
        standard['pressure_hpa'] = pd.to_numeric(df['alti'], errors='coerce') * 33.8639
    
    # Visibility
    if 'vsby' in df.columns:
        standard['visibility_mi'] = pd.to_numeric(df['vsby'], errors='coerce')
    
    # Precipitation: inches to mm
    if 'p01i' in df.columns:
        precip = df['p01i'].replace('T', '0.001')
        standard['precip_mm'] = pd.to_numeric(precip, errors='coerce') * 25.4
    
    # Wind gust: knots to m/s
    if 'gust' in df.columns:
        standard['wind_gust_ms'] = pd.to_numeric(df['gust'], errors='coerce') * 0.51444
    
    # Humidity
    if 'relh' in df.columns:
        standard['humidity_pct'] = pd.to_numeric(df['relh'], errors='coerce')
    
    return standard.sort_values('datetime').reset_index(drop=True)


def process_all_stations(raw_data, verbose=True):
    """Convert all stations to standard format"""
    if verbose:
        print("Processing data...\n")
    
    processed_data = {}
    for station_id, df_raw in raw_data.items():
        df_std = convert_to_standard_format(df_raw, station_id)
        processed_data[station_id] = df_std
        
        if verbose:
            station_name = STATIONS.get(station_id, {}).get('name', station_id)
            print(f"{station_id} - {station_name}:")
            print(f"  Records: {len(df_std):,}")
            
            if 'precip_mm' in df_std.columns:
                precip_valid = df_std['precip_mm'].notna().sum()
                precip_rain = (df_std['precip_mm'] > 0).sum()
                print(f"  Precipitation: {precip_valid:,} valid, {precip_rain:,} with rain")
            print()
    
    if verbose:
        print("✓ Processing complete\n")
    
    return processed_data


# ============================================================================
# PRECIPITATION ANALYSIS
# ============================================================================

def compute_accumulated_rainfall(df):
    """Compute cumulative precipitation"""
    df_accum = df[['datetime', 'precip_mm']].copy()
    df_accum['precip_mm'] = df_accum['precip_mm'].fillna(0)
    df_accum['accumulated_mm'] = df_accum['precip_mm'].cumsum()
    return df_accum


def compute_accumulated_for_all_stations(processed_data):
    """Compute accumulated rainfall for all stations"""
    accumulated_data = {}
    for station_id, df in processed_data.items():
        if 'precip_mm' in df.columns:
            accumulated_data[station_id] = compute_accumulated_rainfall(df)
    return accumulated_data


# ============================================================================
# FILE I/O
# ============================================================================

def save_processed_data(processed_data, output_dir, start_date, end_date, resolution='5min'):
    """Save processed data to CSV"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("\nSaving data...")
    
    # Individual files
    for station_id, df in processed_data.items():
        filename = f"{station_id}_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}_{resolution}.csv"
        df.to_csv(output_dir / filename, index=False)
        print(f"  ✓ {filename}")
    
    # Combined file
    combined = pd.concat(processed_data.values(), ignore_index=True)
    combined = combined.sort_values(['station_id', 'datetime']).reset_index(drop=True)
    combined_filename = f"ALL_STATIONS_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}_{resolution}.csv"
    combined.to_csv(output_dir / combined_filename, index=False)
    print(f"  ✓ {combined_filename}")
    
    print(f"\n✓ Saved to: {output_dir}\n")
