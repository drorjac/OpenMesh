"""
NOAA GHCN-Daily fetcher
=======================

Daily precipitation, snowfall, snow depth, and temperature from NCEI's
Global Historical Climatology Network — Daily.

Source: https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/<STATION>.csv

Raw GHCN-D units (preserved in `fetch_ghcnd_station`):
    PRCP : tenths of mm
    SNOW : mm
    SNWD : mm
    TMAX : tenths of °C
    TMIN : tenths of °C

After `convert_to_metric`:
    precip_amount   [mm]
    snowfall        [cm]
    snow_depth      [cm]   ← matches Mesonet units
    temperature_max [°C]
    temperature_min [°C]
    temperature     [°C]   (mean of max/min)
"""

from io import StringIO
from pathlib import Path

import pandas as pd
import requests


BASE_URL = (
    "https://www.ncei.noaa.gov/data/"
    "global-historical-climatology-network-daily/access"
)

CORE_VARS = ['PRCP', 'SNOW', 'SNWD', 'TMAX', 'TMIN']


# =============================================================================
# FETCH
# =============================================================================

def fetch_ghcnd_station(station_id, start_date=None, end_date=None, verbose=True):
    """Download the full GHCN-Daily CSV for one station and slice to a window.

    Parameters
    ----------
    station_id : str
        GHCN-D station ID, e.g. 'USW00094728' (NYC Central Park).
    start_date, end_date : str | datetime, optional
        Inclusive window. If omitted, returns the entire station record
        (decades to a century-plus).
    verbose : bool

    Returns
    -------
    pd.DataFrame in **raw GHCN-D units** with columns:
        STATION, DATE (as datetime), LATITUDE, LONGITUDE, ELEVATION, NAME,
        PRCP, SNOW, SNWD, TMAX, TMIN  (whichever are present)
    or None on fetch failure.
    """
    url = f"{BASE_URL}/{station_id}.csv"
    if verbose:
        print(f"  {station_id}... ", end='', flush=True)
    try:
        r = requests.get(url, timeout=120)
    except Exception as e:
        if verbose:
            print(f"✗ {e}")
        return None
    if r.status_code != 200 or len(r.text) < 100:
        if verbose:
            print(f"✗ HTTP {r.status_code}")
        return None
    df = pd.read_csv(StringIO(r.text), low_memory=False)
    df['DATE'] = pd.to_datetime(df['DATE'])
    if start_date is not None:
        df = df[df['DATE'] >= pd.to_datetime(start_date)]
    if end_date is not None:
        df = df[df['DATE'] <= pd.to_datetime(end_date)]
    df = df.sort_values('DATE').reset_index(drop=True)
    # Trim to core columns (the file has ~120, most empty for any one station)
    keep = ['STATION', 'DATE', 'LATITUDE', 'LONGITUDE', 'ELEVATION', 'NAME']
    keep += [c for c in CORE_VARS if c in df.columns]
    df = df[keep]
    if verbose:
        print(f"✓ {len(df):,} days")
    return df


def fetch_all_stations(station_ids, start_date=None, end_date=None, verbose=True):
    """Fetch + convert each station. Returns {station_id: DataFrame}."""
    if verbose:
        print(f"Fetching {len(station_ids)} GHCN-Daily station(s)...")
    out = {}
    for sid in station_ids:
        raw = fetch_ghcnd_station(sid, start_date, end_date, verbose=verbose)
        if raw is None or raw.empty:
            continue
        out[sid] = convert_to_metric(raw, sid)
    if verbose:
        print(f"✓ Got {len(out)}/{len(station_ids)} stations")
    return out


# =============================================================================
# UNIT CONVERSION
# =============================================================================

def convert_to_metric(df, station_id):
    """Apply GHCN-D unit conversions and standardize column names.

    Column-name choices match the WU PWS / Mesonet conventions so the same
    `analysis.pws_qc.network_resample(var=...)` calls work across all sources.
    """
    out = pd.DataFrame()
    out['datetime']   = pd.to_datetime(df['DATE'])
    out['station_id'] = station_id
    if 'LATITUDE' in df:
        out['lat']  = pd.to_numeric(df['LATITUDE'], errors='coerce')
    if 'LONGITUDE' in df:
        out['lon']  = pd.to_numeric(df['LONGITUDE'], errors='coerce')
    if 'ELEVATION' in df:
        out['elev'] = pd.to_numeric(df['ELEVATION'], errors='coerce')
    if 'PRCP' in df:
        out['precip_amount']   = pd.to_numeric(df['PRCP'], errors='coerce') / 10.0  # tenths mm → mm
    if 'SNOW' in df:
        out['snowfall']        = pd.to_numeric(df['SNOW'], errors='coerce') / 10.0  # mm → cm
    if 'SNWD' in df:
        out['snow_depth']      = pd.to_numeric(df['SNWD'], errors='coerce') / 10.0  # mm → cm
    if 'TMAX' in df:
        out['temperature_max'] = pd.to_numeric(df['TMAX'], errors='coerce') / 10.0  # tenths °C → °C
    if 'TMIN' in df:
        out['temperature_min'] = pd.to_numeric(df['TMIN'], errors='coerce') / 10.0
    if 'temperature_max' in out and 'temperature_min' in out:
        out['temperature'] = (out['temperature_max'] + out['temperature_min']) / 2.0
    return out


# =============================================================================
# CONVERT TO XARRAY / NETCDF (compatible with analysis.netcdf_utils)
# =============================================================================

def to_xarray_dict(processed_data):
    """{sid: DataFrame} -> {sid: xr.Dataset}; see src/netCDF_converters/noaa_daily_to_netcdf.py."""
    return _converter().to_xarray_dict(processed_data)


def save_netcdf(processed_data, output_path, verbose=True):
    """Grouped OpenSense netCDF; see src/netCDF_converters/noaa_daily_to_netcdf.py."""
    return _converter().noaa_daily_to_netcdf(processed_data, output_path, verbose=verbose)


def _converter():
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'netCDF_converters'))
    import noaa_daily_to_netcdf
    return noaa_daily_to_netcdf


def save_csv(processed_data, output_dir, prefix='noaa_daily',
             save_individual=True, save_combined=True, verbose=True):
    """Save per-station + combined CSVs."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {'individual': [], 'combined': None}
    if save_individual:
        for sid, df in processed_data.items():
            fpath = output_dir / f'{sid}_{prefix}.csv'
            df.to_csv(fpath, index=False)
            paths['individual'].append(fpath)
            if verbose:
                print(f"  ✓ {fpath.name} ({len(df):,} rows)")
    if save_combined and processed_data:
        combined = pd.concat(processed_data.values(), ignore_index=True)
        cpath = output_dir / f'{prefix}_combined.csv'
        combined.to_csv(cpath, index=False)
        paths['combined'] = cpath
        if verbose:
            print(f"  ✓ {cpath.name} ({len(combined):,} rows)")
    return paths
