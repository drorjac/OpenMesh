"""
Convert downloaded WU airport CSV files to NetCDF format.

Fixes:
  1. Units: imperial → metric (°F→°C, mph→m/s, inHg→hPa, in→mm)
  2. Time: local Eastern (EST/EDT) → UTC unix epoch

Input:  <csv_dir>/<STATION>_combined.csv for KJFK and KLGA
        (default csv_dir: dataset/raw/fetched/wu)
Output: grouped netCDF (default dataset/raw/full/airport_wu_dates.nc)
  - Same group-per-station structure as pws_wu_network.nc
  - Variables: time, id, lat, lon, rainfall_amount, precip_rate_calculated,
               temperature, dew_point, relative_humidity, wind_direction,
               wind_velocity, wind_gust, air_pressure, condition

Usage (CLI):
    python airport_wu_csv_to_netcdf.py [--csv-dir DIR] [--out FILE.nc]
Usage (import):
    from airport_wu_csv_to_netcdf import process_station, write_nc
"""

import argparse
from pathlib import Path
import numpy as np
import pandas as pd
import netCDF4 as nc4
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------------------
# Station metadata (from pws_wu_network.nc)
# ---------------------------------------------------------------------------
STATION_META = {
    'KJFK': {'lat': 40.70,  'lon': -73.80},
    'KLGA': {'lat': 40.76,  'lon': -73.86},
}

DEFAULT_CSV_DIR = Path('dataset/raw/fetched/wu')
DEFAULT_OUT_FILE = Path('dataset/raw/full/airport_wu_dates.nc')

EASTERN = ZoneInfo('America/New_York')
UTC     = ZoneInfo('UTC')

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
WIND_DIR_DEG = {
    'N': 0, 'NNE': 22.5, 'NE': 45, 'ENE': 67.5,
    'E': 90, 'ESE': 112.5, 'SE': 135, 'SSE': 157.5,
    'S': 180, 'SSW': 202.5, 'SW': 225, 'WSW': 247.5,
    'W': 270, 'WNW': 292.5, 'NW': 315, 'NNW': 337.5,
    'CALM': 0, 'VAR': np.nan,
}


def _strip(series: pd.Series) -> pd.Series:
    """Strip non-breaking spaces, '°', unit suffixes; return float."""
    return (
        series.astype(str)
              .str.replace('\xa0', '', regex=False)
              .str.replace('°', '', regex=False)
              .str.replace(r'\s*(F|C|mph|in|hPa|%|mb)', '', regex=True)
              .str.strip()
              .replace({'': np.nan, 'N/A': np.nan, '--': np.nan})
              .astype(float)
    )


def f_to_c(f: pd.Series) -> pd.Series:
    return (_strip(f) - 32) * 5 / 9


def mph_to_ms(mph: pd.Series) -> pd.Series:
    return _strip(mph) * 0.44704


def inhg_to_hpa(inhg: pd.Series) -> pd.Series:
    return _strip(inhg) * 33.8639


def in_to_mm(inches: pd.Series) -> pd.Series:
    return _strip(inches) * 25.4


def wind_text_to_deg(series: pd.Series) -> pd.Series:
    return series.str.strip().map(WIND_DIR_DEG).astype(float)


def local_eastern_to_utc_unix(dt_series: pd.Series) -> np.ndarray:
    """Parse datetime strings as Eastern local time, return UTC unix timestamps."""
    out = []
    epoch = pd.Timestamp('1970-01-01', tz='UTC')
    for raw in dt_series:
        ts = pd.Timestamp(raw).tz_localize(EASTERN, ambiguous='NaT', nonexistent='NaT')
        if ts is pd.NaT or ts is None:
            out.append(np.nan)
        else:
            ts_utc = ts.tz_convert('UTC')
            out.append((ts_utc - epoch).total_seconds())
    return np.array(out, dtype=np.float64)


# ---------------------------------------------------------------------------
# Per-station processing
# ---------------------------------------------------------------------------
def process_station(station_id: str, csv_dir: Path = DEFAULT_CSV_DIR) -> dict:
    csv_path = Path(csv_dir) / f'{station_id}_combined.csv'
    df = pd.read_csv(csv_path)

    # Time → UTC unix
    unix = local_eastern_to_utc_unix(df['DateTime'])
    valid = ~np.isnan(unix)
    df = df[valid].copy()
    unix = unix[valid]

    # Sort by time
    order = np.argsort(unix)
    unix = unix[order]
    df = df.iloc[order].reset_index(drop=True)

    temperature = f_to_c(df['Temperature']).values
    dew_point   = f_to_c(df['Dew Point']).values
    humidity    = _strip(df['Humidity']).values
    wind_dir    = wind_text_to_deg(df['Wind']).values
    wind_speed  = mph_to_ms(df['Wind Speed']).values
    wind_gust   = mph_to_ms(df['Wind Gust']).values
    pressure    = inhg_to_hpa(df['Pressure']).values
    precip_mm   = in_to_mm(df['Precip.']).values
    condition   = df['Condition'].fillna('').values.astype(str)

    # precip_rate: hourly obs, so rate ≈ amount per hour
    precip_rate = precip_mm.copy()

    # Physical range clipping (bad downloaded values → NaN)
    def clip_nan(arr, lo=None, hi=None):
        arr = arr.copy()
        if lo is not None: arr[arr < lo] = np.nan
        if hi is not None: arr[arr > hi] = np.nan
        return arr

    wind_speed   = clip_nan(wind_speed,  hi=70)
    wind_gust    = clip_nan(wind_gust,   hi=70)
    pressure     = clip_nan(pressure,    lo=870, hi=1090)
    temperature  = clip_nan(temperature, lo=-60, hi=60)
    dew_point    = clip_nan(dew_point,   lo=-60, hi=60)

    return {
        'unix':         unix,
        'temperature':  temperature,
        'dew_point':    dew_point,
        'humidity':     humidity,
        'wind_dir':     wind_dir,
        'wind_speed':   wind_speed,
        'wind_gust':    wind_gust,
        'pressure':     pressure,
        'precip_mm':    precip_mm,
        'precip_rate':  precip_rate,
        'condition':    condition,
    }


# ---------------------------------------------------------------------------
# Write NetCDF
# ---------------------------------------------------------------------------
def write_nc(out_path: Path, stations: dict[str, dict]):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ds = nc4.Dataset(str(out_path), 'w', format='NETCDF4')
    ds.description = 'WU airport stations, units corrected, time converted to UTC'
    ds.source = 'Weather Underground downloaded CSV → NetCDF'

    for sid, meta in STATION_META.items():
        if sid not in stations:
            continue
        d = stations[sid]
        n = len(d['unix'])

        grp = ds.createGroup(sid)
        grp.createDimension('time', n)
        grp.createDimension('station', 1)

        # time
        tv = grp.createVariable('time', 'f8', ('time',))
        tv.units    = 'seconds since 1970-01-01 00:00:00 UTC'
        tv.calendar = 'standard'
        tv[:]       = d['unix']

        # id
        idv = grp.createVariable('id', str, ('station',))
        idv[0] = sid

        # lat / lon
        latv = grp.createVariable('lat', 'f4', ('station',))
        latv.units = 'degrees_in_WGS84_projection'
        latv[0]    = meta['lat']

        lonv = grp.createVariable('lon', 'f4', ('station',))
        lonv.units = 'degrees_in_WGS84_projection'
        lonv[0]    = meta['lon']

        def add_var(name, units, data, fill=np.nan):
            v = grp.createVariable(name, 'f4', ('station', 'time'), fill_value=fill)
            v.units = units
            v[0, :] = data

        add_var('rainfall_amount',       'mm',    d['precip_mm'])
        add_var('precip_rate_calculated','mm h-1', d['precip_rate'])
        add_var('temperature',           'degrees_celsius', d['temperature'])
        add_var('dew_point',             'degrees_celsius', d['dew_point'])
        add_var('relative_humidity',     '%',      d['humidity'])
        add_var('wind_direction',        'degrees', d['wind_dir'])
        add_var('wind_velocity',         'ms-1',   d['wind_speed'])
        add_var('wind_gust',             'ms-1',   d['wind_gust'])
        add_var('air_pressure',          'hPa',    d['pressure'])

        # condition (string)
        cv = grp.createVariable('condition', str, ('time',))
        for i, cond in enumerate(d['condition']):
            cv[i] = cond

        print(f'  {sid}: {n} obs  {_ts(d["unix"][0])} → {_ts(d["unix"][-1])}')

    ds.close()


def _ts(unix):
    import datetime
    return datetime.datetime.utcfromtimestamp(float(unix)).strftime('%Y-%m-%d %H:%M UTC')


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0].strip())
    ap.add_argument('--csv-dir', type=Path, default=DEFAULT_CSV_DIR,
                    help=f'folder with <STATION>_combined.csv (default {DEFAULT_CSV_DIR})')
    ap.add_argument('--out', type=Path, default=DEFAULT_OUT_FILE,
                    help=f'output netCDF (default {DEFAULT_OUT_FILE})')
    args = ap.parse_args(argv)

    if not args.csv_dir.is_dir():
        raise SystemExit(f'CSV folder not found: {args.csv_dir} (pass --csv-dir)')

    print('Processing stations...')
    stations = {}
    for sid in STATION_META:
        csv_path = args.csv_dir / f'{sid}_combined.csv'
        if not csv_path.exists():
            print(f'  {sid}: {csv_path} not found, skipping')
            continue
        print(f'  Reading {csv_path.name}...')
        stations[sid] = process_station(sid, args.csv_dir)
    if not stations:
        raise SystemExit(f'No <STATION>_combined.csv files for {sorted(STATION_META)} in {args.csv_dir}')

    print(f'\nWriting {args.out}...')
    write_nc(args.out, stations)
    print('Done.')


if __name__ == '__main__':
    main()
