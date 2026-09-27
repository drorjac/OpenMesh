"""
Write processed NOAA ASOS 1-min data as a FLAT (id, time) OpenSense-PWS-v1.0 netCDF.

All stations share one aligned time axis (union of timestamps, NaN-filled). This is
the layout of dataset/raw/full/asos_nyc_network.nc and of the fetch pipeline
(`asos_fetch.convert_asos_csv_to_netcdf`). The grouped alternative (one netCDF4 group
per station) is `asos_to_netcdf.py`; `analysis.nycmesh_utils.load_weather_networks`
reads both.

Variables: rainfall_amount, rainfall_rate, temperature, dewpoint, wind_velocity,
wind_direction, wind_gust, wind_gust_direction, precip_type, precip_category (the
present-weather codes the gauge-melt QC needs).

Usage (CLI, from an ASOS_standard_*.csv written by asos_fetch.fetch_and_save_asos):
    python asos_flat_to_netcdf.py <input_csv> <output.nc> [--stations-csv PATH]

Usage (import):
    from asos_flat_to_netcdf import asos_flat_to_netcdf
    asos_flat_to_netcdf({station: DataFrame}, meta, output_path)
"""
import argparse
import os
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

DEFAULT_STATIONS_CSV = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "dataset", "meta", "ASOS_stations.csv")


def asos_flat_to_netcdf(
    processed_data,
    meta,
    output_path,
    verbose=True,
):
    """Save processed ASOS data as flat (id, time) NetCDF — OpenSense v1.0.

    All stations share a common aligned time axis (union of all timestamps).
    Stations missing a given timestamp are NaN-filled. This matches the
    OpenSense convention for sources with the same reporting schedule.

    Parameters
    ----------
    processed_data : dict
        {station_id: pd.DataFrame} — output of process_all_stations().
        DataFrame must have a 'datetime' column or DatetimeIndex.
    meta : pd.DataFrame
        Station metadata indexed by Station ID, columns: Latitude, Longitude, Elevation.
    output_path : path-like
        Destination .nc file (parent dir created automatically).
    verbose : bool
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    meta = meta.rename(index=lambda s: s[1:] if len(s) == 4 and s.startswith('K') else s)  # 'KJFK' ↔ 'JFK'

    # Normalize: time-indexed, no station_id column, deduped
    indexed = {}
    for sid, df in processed_data.items():
        df = df.copy()
        if not isinstance(df.index, pd.DatetimeIndex):
            df = df.set_index('datetime')
        df = df.drop(columns=['station_id'], errors='ignore')
        df = df.sort_index()
        df = df[~df.index.duplicated(keep='first')]
        indexed[sid] = df

    # Common time axis — union of all station timestamps
    all_times = sorted(set().union(*[df.index.tolist() for df in indexed.values()]))

    ids   = list(indexed.keys())
    lats  = [float(meta.loc[sid, 'Latitude'])  if sid in meta.index else np.nan for sid in ids]
    lons  = [float(meta.loc[sid, 'Longitude']) if sid in meta.index else np.nan for sid in ids]
    elevs = [float(meta.loc[sid, 'Elevation']) if sid in meta.index else np.nan for sid in ids]

    # (csv_col, netcdf_name, attrs) — decouples source names from OpenSense canonical names
    VAR_DEFS = [
        ('precip_amount',  'rainfall_amount', {'units': 'mm',              'long_name': 'rainfall_amount_per_time_unit'}),
        ('precip_rate',    'rainfall_rate',   {'units': 'mm h-1',          'long_name': 'precipitation_rate_calculated'}),
        ('temperature',    'temperature',     {'units': 'degrees_celsius',  'long_name': 'air_temperature'}),
        ('dewpoint',       'dewpoint',        {'units': 'degrees_celsius',  'long_name': 'dewpoint_temperature'}),
        ('wind_speed',     'wind_velocity',   {'units': 'ms-1',             'long_name': 'average_wind_speed'}),
        ('wind_direction', 'wind_direction',  {'units': 'degrees',          'long_name': 'wind_direction'}),
        ('wind_gust',      'wind_gust',       {'units': 'ms-1',             'long_name': 'wind_gust_speed'}),
        ('wind_gust_direction', 'wind_gust_direction', {'units': 'degrees',     'long_name': 'wind_gust_direction'}),
    ]
    # present-weather codes: needed by the ASOS gauge-melt QC and phase analysis
    STR_DEFS = [
        ('precip_type',     'precip_type',     {'long_name': 'ASOS present-weather precipitation code (e.g. R-, S, NP, M)'}),
        ('precip_category', 'precip_category', {'long_name': 'precipitation category: dry/rain/snow/ice/mix/missing'}),
    ]

    # Build (id, time) arrays — reindex each station onto common axis
    data_vars = {}
    for csv_col, nc_name, attrs in VAR_DEFS:
        rows = []
        for sid in ids:
            df = indexed[sid]
            row = df[csv_col].reindex(all_times).values if csv_col in df.columns else np.full(len(all_times), np.nan)
            rows.append(row)
        data_vars[nc_name] = (['id', 'time'], np.vstack(rows), attrs)
    for csv_col, nc_name, attrs in STR_DEFS:
        if not any(csv_col in df.columns for df in indexed.values()):
            continue
        # plain numpy strings: pandas >= 3 hands back Arrow arrays netCDF4 cannot write
        rows = [indexed[sid][csv_col].reindex(all_times).fillna('').to_numpy(dtype=str)
                if csv_col in indexed[sid].columns else np.full(len(all_times), '')
                for sid in ids]
        data_vars[nc_name] = (['id', 'time'], np.vstack(rows), attrs)

    t0 = pd.to_datetime(all_times[0])
    t1 = pd.to_datetime(all_times[-1])

    ds = xr.Dataset(
        data_vars,
        coords={
            'id':   ('id',   ids,   {'long_name': 'personal_weather_station_identifier'}),
            'time': ('time', all_times),
            'lat':  ('id',   lats,  {'units': 'degrees_in_WGS84_projection', 'long_name': 'latitude'}),
            'lon':  ('id',   lons,  {'units': 'degrees_in_WGS84_projection', 'long_name': 'longitude'}),
            'elev': ('id',   elevs, {'units': 'metres_above_sea',            'long_name': 'ground_elevation_above_sea_level'}),
        },
        attrs={
            'title':        'NOAA ASOS 1-min Weather Data — NYC Metro Area',
            'institution':  'NOAA / Iowa Environmental Mesonet (IEM)',
            'source':       'NOAA ASOS 1-min via Iowa Environmental Mesonet (IEM)',
            'Conventions':  'OpenSense-PWS-v1.0',
            'start_date':   t0.strftime('%Y-%m-%d'),
            'end_date':     t1.strftime('%Y-%m-%d'),
            'time_range':   f'{t0.isoformat()} / {t1.isoformat()}',
            'date_created': pd.Timestamp.now().strftime('%Y-%m-%d'),
            'license':      'Public domain (NOAA)',
            'reference':    'https://mesonet.agron.iastate.edu/request/asos/1min.phtml',
            'comment': (
                'ASOS stations in the NYC metro area. '
                'rainfall_amount includes all precipitation types (rain, snow, etc.), not only rainfall. '
                'Common 1-min time axis; gaps NaN-filled (empty string for codes). All timestamps UTC.'
            ),
        },
    )

    encoding = {
        v: {'zlib': True, 'complevel': 4}
        for v, var in ds.data_vars.items()
        if var.dtype.kind in ('f', 'i', 'u')
    }
    encoding['time'] = {'units': 'seconds since 1970-01-01 00:00:00 UTC', 'dtype': 'float64'}
    ds.attrs['history'] = (f"{pd.Timestamp.now('UTC'):%Y-%m-%dT%H:%M:%SZ}: written by "
                           "src/netCDF_converters/asos_flat_to_netcdf.py")
    ds.to_netcdf(output_path, encoding=encoding, engine='netcdf4', unlimited_dims=['time'])

    if verbose:
        size_mb = output_path.stat().st_size / 1e6
        print(f"  Saved : {output_path.name}  ({size_mb:.1f} MB)")
        print(f"  Dims  : id={len(ids)}, time={len(all_times):,}")
        print(f"  Period: {t0.date()} → {t1.date()}")
        print(f"  Stations ({len(ids)}): {ids}")

    return output_path


def csv_to_flat_netcdf(input_csv, output_path, stations_csv=DEFAULT_STATIONS_CSV, verbose=True):
    """ASOS_standard_*.csv → flat netCDF (reads station lat/lon/elev from `stations_csv`)."""
    df_all = pd.read_csv(input_csv, dtype={'station_id': str})
    df_all['datetime'] = pd.to_datetime(df_all['datetime'])
    processed = {sid: g.set_index('datetime').drop(columns=['station_id'])
                 for sid, g in df_all.groupby('station_id')}
    meta = pd.read_csv(stations_csv).set_index('Station ID')
    return asos_flat_to_netcdf(processed, meta, output_path, verbose=verbose)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('input_csv', help='ASOS_standard_*.csv (from asos_fetch.py)')
    ap.add_argument('output_nc', help='output .nc path')
    ap.add_argument('--stations-csv', default=DEFAULT_STATIONS_CSV)
    a = ap.parse_args()
    csv_to_flat_netcdf(a.input_csv, a.output_nc, a.stations_csv)


if __name__ == '__main__':
    main()
